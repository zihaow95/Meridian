"""Safety tests for the isolated clean-database seed verifier."""

from __future__ import annotations

import pytest

from tests.identity import verify_e2e_seed_cold_start as verifier


class CreateFailsCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statements.append(statement)
        if statement.startswith("CREATE DATABASE"):
            raise RuntimeError("database already exists")

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self, cursor: CreateFailsCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def autocommit(self, enabled: bool) -> None:
        assert enabled is True

    def cursor(self) -> CreateFailsCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class CloseFailsCursor(CreateFailsCursor):
    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def close(self) -> None:
        self.closed = True
        raise RuntimeError("cursor close failed")


class CloseFailsConnection(FakeConnection):
    def close(self) -> None:
        self.closed = True
        raise RuntimeError("connection close failed")


def test_create_failure_never_drops_database_not_owned_by_verifier(monkeypatch) -> None:
    cursor = CreateFailsCursor()
    connection = FakeConnection(cursor)
    monkeypatch.setenv("MYSQL_ROOT_PASSWORD", "test-root-password")
    monkeypatch.setattr(verifier.MySQLdb, "connect", lambda **_: connection)
    monkeypatch.setattr(
        verifier,
        "run_manage",
        lambda *_, **__: pytest.fail("manage.py must not run after CREATE failure"),
    )

    with pytest.raises(RuntimeError, match="database already exists"):
        verifier.main()

    assert not any(statement.startswith("DROP DATABASE") for statement in cursor.statements)
    assert cursor.closed is True
    assert connection.closed is True


def test_close_failures_do_not_mask_primary_migration_error(monkeypatch, capsys) -> None:
    cursor = CloseFailsCursor()
    connection = CloseFailsConnection(cursor)

    def fail_migration(*_: object, **__: object) -> None:
        raise RuntimeError("migration failed")

    monkeypatch.setenv("MYSQL_ROOT_PASSWORD", "test-root-password")
    monkeypatch.setattr(verifier.MySQLdb, "connect", lambda **_: connection)
    monkeypatch.setattr(verifier, "run_manage", fail_migration)

    with pytest.raises(RuntimeError, match="migration failed"):
        verifier.main()

    assert any(statement.startswith("DROP DATABASE") for statement in cursor.statements)
    assert cursor.closed is True
    assert connection.closed is True
    captured = capsys.readouterr()
    assert "cursor close failed" in captured.err
    assert "connection close failed" in captured.err
