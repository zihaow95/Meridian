"""The database, not the application, decides who wins a race.

`notifications_todo_open_dedup_uniq` was declared with `condition=`, which MySQL
cannot create: Django emits W036 and skips it, so two concurrent projections of
the same source could both create an open todo. The uniqueness is re-expressed
with the nullable sentinel column the rest of the repository uses.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.identity.models.user import User
from apps.notifications.models import Todo, TodoStatus

pytestmark = pytest.mark.django_db


def build_todo(user: User, dedup_key: str, **overrides: object) -> Todo:
    status = overrides.pop("status", TodoStatus.OPEN)
    defaults: dict[str, object] = {
        "organization": user.organization,
        "assignee": user,
        "todo_type": "review",
        "source_type": "identity.user",
        "source_id": user.public_id,
        "action_code": "identity.user.review",
        "status": status,
        "dedup_key": dedup_key,
        "deep_link": f"/users/{user.public_id}",
        "title": "Review user status change",
        "open_slot": 1 if status == TodoStatus.OPEN else None,
    }
    return Todo.objects.create(**{**defaults, **overrides})


def test_an_open_todo_occupies_the_dedup_sentinel(active_user) -> None:
    todo = build_todo(active_user, "review:one")

    assert todo.open_slot == 1


def test_database_refuses_a_second_open_todo_for_the_same_dedup_key(active_user) -> None:
    build_todo(active_user, "review:one")

    with pytest.raises(IntegrityError), transaction.atomic():
        build_todo(active_user, "review:one")


def test_a_closed_todo_releases_the_dedup_key_for_a_new_one(active_user) -> None:
    first = build_todo(active_user, "review:one")
    first.status = TodoStatus.COMPLETED
    first.open_slot = None
    first.save(update_fields=["status", "open_slot", "updated_at"])

    replacement = build_todo(active_user, "review:one")

    assert replacement.open_slot == 1
    assert Todo.objects.filter(assignee=active_user, dedup_key="review:one").count() == 2


def test_history_may_hold_many_settled_todos_for_one_dedup_key(active_user) -> None:
    build_todo(active_user, "review:one", status=TodoStatus.COMPLETED)
    build_todo(active_user, "review:one", status=TodoStatus.CANCELLED)
    build_todo(active_user, "review:one", status=TodoStatus.EXPIRED)

    assert Todo.objects.filter(dedup_key="review:one", open_slot=None).count() == 3


def test_two_assignees_may_each_hold_the_same_dedup_key(active_user, another_active_user) -> None:
    build_todo(active_user, "review:one")
    build_todo(another_active_user, "review:one")

    assert Todo.objects.filter(dedup_key="review:one", open_slot=1).count() == 2
