"""Transactional audit guarantees."""

from __future__ import annotations

import pytest

from apps.audit.services.append_event import AuditWriteFailed
from apps.identity.models.user import UserStatus
from apps.identity.services.change_user_status import ChangeUserStatus


def _raise_audit_write_failed(*args: object, **kwargs: object) -> None:
    raise AuditWriteFailed("audit insert failed")


@pytest.mark.django_db(transaction=True)
def test_critical_command_rolls_back_when_audit_write_fails(
    active_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.identity.services.change_user_status.append_event", _raise_audit_write_failed
    )
    with pytest.raises(AuditWriteFailed):
        ChangeUserStatus(
            actor=active_user,
            target=active_user,
            status=UserStatus.DISABLED,
        ).execute()
    active_user.refresh_from_db()
    assert active_user.status == UserStatus.ACTIVE
