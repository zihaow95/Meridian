"""Verify E2E seed first-run and repeat-run behavior on a clean MySQL database."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import MySQLdb

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required for clean E2E seed verification.")
    return value


def run_manage(*args: str, env: dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, "manage.py", *args, "--settings=config.settings.test"],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
    )


def main() -> int:
    root_password = required_env("MYSQL_ROOT_PASSWORD")
    database_name = f"meridian_seed_verify_{uuid.uuid4().hex[:12]}"
    if not DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise RuntimeError("Generated verification database name is unsafe.")

    connection = MySQLdb.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user="root",
        passwd=root_password,
    )
    connection.autocommit(True)
    cursor = connection.cursor()

    child_env = os.environ.copy()
    child_env.update(
        {
            "MYSQL_DATABASE": database_name,
            "MYSQL_TEST_DATABASE": database_name,
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": root_password,
        }
    )

    try:
        cursor.execute(
            f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
        run_manage("migrate", "--noinput", env=child_env)
        run_manage("seed_e2e_user", env=child_env)

        cursor.execute(f"SELECT COUNT(*) FROM `{database_name}`.`authorization_role_assignment`")
        first_assignment_count = int(cursor.fetchone()[0])
        if first_assignment_count == 0:
            raise RuntimeError("First seed created no role assignments.")

        run_manage("seed_e2e_user", env=child_env)

        cursor.execute(f"SELECT COUNT(*) FROM `{database_name}`.`authorization_role_assignment`")
        second_assignment_count = int(cursor.fetchone()[0])
        if second_assignment_count != first_assignment_count:
            raise RuntimeError(
                "Repeat seed changed role-assignment count: "
                f"{first_assignment_count} -> {second_assignment_count}."
            )

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM `{database_name}`.`authorization_role_assignment`
            WHERE scope_id IS NULL OR scope_key = ''
            """
        )
        invalid_scope_count = int(cursor.fetchone()[0])
        if invalid_scope_count:
            raise RuntimeError(
                f"Seed created {invalid_scope_count} role assignments with invalid scope fields."
            )

        print(
            "Clean E2E seed verification passed: "
            f"{first_assignment_count} normalized role assignments, repeat-run stable."
        )
        return 0
    finally:
        cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        cursor.close()
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
