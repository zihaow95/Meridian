"""Category, level, summary and channels come from published configuration.

A notification that invents its own wording or its own channel list cannot be
explained afterwards, and a template that is free to interpolate arbitrary
fields is a way to leak an object's body into a summary. Both are decided by a
pinned configuration version, and anything outside the declared variables is
refused rather than rendered.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.configuration.models import ConfigurationStatus, ConfigurationVersion
from apps.notifications.models import (
    DeliveryChannel,
    Notification,
    NotificationStatus,
)
from apps.notifications.services.notifications import CreateInAppNotification
from apps.notifications.services.policies import (
    NotificationPolicyUnavailable,
    NotificationTemplateUnavailable,
    resolve_notification,
)
from tests.notifications.conftest import TODO_TEMPLATE as TEMPLATE

pytestmark = pytest.mark.django_db


@pytest.fixture
def templates(notification_templates: Any) -> Any:
    return notification_templates


@pytest.fixture
def policy(notification_policy: Any) -> Any:
    return notification_policy


def resolve(organization, **overrides: Any):
    kwargs: dict[str, Any] = {
        "organization": organization,
        "template_code": "todo.created",
        "variables": {"title": "复核用户状态"},
    }
    return resolve_notification(**{**kwargs, **overrides})


def test_the_template_decides_category_level_and_wording(organization, templates, policy) -> None:
    template_version = templates()
    policy_version = policy()

    resolved = resolve(organization)

    assert resolved.category == "ACTION_REQUIRED"
    assert resolved.level == "IMPORTANT"
    assert resolved.summary == "待办 复核用户状态 需要处理"
    assert resolved.template_version_id == template_version.id
    assert resolved.policy_version_id == policy_version.id


def test_the_resolution_pins_the_channel_rule_it_acted_on(organization, templates, policy) -> None:
    policy()
    templates()

    resolved = resolve(organization)

    assert resolved.channels == ("IN_APP",)
    assert resolved.policy_snapshot == {
        "category": "ACTION_REQUIRED",
        "level": "IMPORTANT",
        "channels": ["IN_APP"],
    }


def test_a_caller_cannot_override_the_published_template_level(
    organization, templates, policy
) -> None:
    """Business facts do not carry a level; the template catalog owns the class."""

    templates()
    policy(
        [
            {"category": "ACTION_REQUIRED", "level": "IMPORTANT", "channels": ["IN_APP"]},
            {"category": "ACTION_REQUIRED", "level": "URGENT", "channels": ["IN_APP"]},
        ]
    )

    with pytest.raises(TypeError):
        resolve(organization, level="URGENT")

    resolved = resolve(organization)
    assert resolved.level == "IMPORTANT"


def test_an_unknown_template_code_is_refused(organization, templates, policy) -> None:
    templates()
    policy()

    with pytest.raises(NotificationTemplateUnavailable) as excinfo:
        resolve(organization, template_code="todo.invented")

    assert "todo.invented" in str(excinfo.value)


def test_a_missing_template_catalog_is_refused(organization, policy) -> None:
    policy()

    with pytest.raises(NotificationTemplateUnavailable):
        resolve(organization)


def test_a_draft_template_catalog_does_not_count_as_published(
    organization, active_user, templates, policy
) -> None:
    policy()
    published = templates()
    ConfigurationVersion.objects.create(
        organization=organization,
        definition=published.definition,
        version_number=published.version_number + 1,
        status=ConfigurationStatus.DRAFT,
        content_json={"templates": [{**TEMPLATE, "summary_template": "草稿 {title}"}]},
        created_by=active_user,
    )

    resolved = resolve(organization)

    assert resolved.summary == "待办 复核用户状态 需要处理"
    assert resolved.template_version_id == published.id


def test_a_variable_the_template_never_declared_is_refused(organization, templates, policy) -> None:
    """This is the leak path: an undeclared variable is somebody's object body."""

    templates()
    policy()

    with pytest.raises(ValueError) as excinfo:
        resolve(
            organization,
            variables={"title": "复核用户状态", "id_card_number": "310000199001010001"},
        )

    assert "id_card_number" in str(excinfo.value)


def test_a_template_that_asks_for_an_undeclared_variable_is_refused(
    organization, templates, policy
) -> None:
    templates([{**TEMPLATE, "summary_template": "待办 {title} 金额 {contract_amount}"}])
    policy()

    with pytest.raises(ValueError) as excinfo:
        resolve(organization)

    assert "contract_amount" in str(excinfo.value)


def test_a_declared_variable_with_no_value_is_refused(organization, templates, policy) -> None:
    templates()
    policy()

    with pytest.raises(ValueError):
        resolve(organization, variables={})


def test_a_missing_delivery_policy_is_refused(organization, templates) -> None:
    templates()

    with pytest.raises(NotificationPolicyUnavailable):
        resolve(organization)


def test_a_policy_without_a_rule_for_this_class_is_refused(organization, templates, policy) -> None:
    templates()
    policy([{"category": "INFORMATION", "level": "NORMAL", "channels": ["IN_APP"]}])

    with pytest.raises(NotificationPolicyUnavailable) as excinfo:
        resolve(organization)

    assert "ACTION_REQUIRED" in str(excinfo.value)


@pytest.mark.parametrize(
    "category",
    [
        "ACTION_REQUIRED",
        "DEADLINE",
        "BUSINESS_ALERT",
        "PROCESS_RESULT",
        "SYSTEM_FAILURE",
        "INFORMATION",
    ],
)
@pytest.mark.parametrize("level", ["URGENT", "IMPORTANT", "NORMAL"])
def test_every_category_and_level_pair_resolves(
    organization, templates, policy, category: str, level: str
) -> None:
    templates([{**TEMPLATE, "category": category, "default_level": level}])
    policy([{"category": category, "level": level, "channels": ["IN_APP"]}])

    resolved = resolve(organization)

    assert (resolved.category, resolved.level) == (category, level)
    assert resolved.channels == ("IN_APP",)


def create(active_user, todo, **overrides: Any) -> Notification | None:
    kwargs: dict[str, Any] = {
        "recipient": active_user,
        "template_code": "todo.created",
        "variables": {"title": todo.title},
        "object_type": todo.source_type,
        "object_id": todo.source_id,
        "dedup_key": f"notify:{todo.dedup_key}",
        "deep_link": todo.deep_link,
        "todo": todo,
    }
    return CreateInAppNotification(**{**kwargs, **overrides}).execute()


def test_a_created_notification_records_the_class_and_the_versions_that_decided_it(
    active_user, todo, allow_notification, templates, policy
) -> None:
    template_version = templates()
    policy_version = policy()

    notification = create(active_user, todo)

    assert notification is not None
    assert notification.category == "ACTION_REQUIRED"
    assert notification.level == "IMPORTANT"
    assert notification.summary == f"待办 {todo.title} 需要处理"
    assert notification.status == NotificationStatus.UNREAD
    assert notification.template_version_id == template_version.id
    assert notification.policy_version_id == policy_version.id
    assert notification.policy_snapshot["channels"] == ["IN_APP"]


def test_creation_only_opens_the_in_app_channel_in_this_phase(
    active_user, todo, allow_notification, templates, policy
) -> None:
    templates()
    policy()

    notification = create(active_user, todo)

    assert notification is not None
    assert [delivery.channel for delivery in notification.deliveries.all()] == [
        DeliveryChannel.IN_APP
    ]


def test_creation_refuses_a_summary_variable_the_template_never_declared(
    active_user, todo, allow_notification, templates, policy
) -> None:
    templates()
    policy()

    with pytest.raises(ValueError):
        create(active_user, todo, variables={"title": todo.title, "salary": "42000"})

    assert Notification.objects.count() == 0


def test_a_denied_recipient_is_not_notified_and_no_configuration_is_read(
    active_user, todo, monkeypatch
) -> None:
    """Nothing is published here: a denied recipient must fail closed, not on config."""

    monkeypatch.setattr(
        "apps.notifications.services.notifications.authorize",
        lambda *args, **kwargs: type("D", (), {"allowed": False})(),
    )

    assert create(active_user, todo) is None
    assert Notification.objects.count() == 0


def test_replaying_the_same_dedup_key_does_not_create_a_second_notification(
    active_user, todo, allow_notification, templates, policy
) -> None:
    templates()
    policy()

    first = create(active_user, todo)
    second = create(active_user, todo)

    assert first is not None and second is not None
    assert first.pk == second.pk
    assert Notification.objects.count() == 1


def test_a_todo_requested_event_cannot_override_the_template_level(
    active_user, event, todo_consumer, allow_notification, templates, policy
) -> None:
    """Even a payload that still carries `level` must use the published default."""

    templates()
    policy(
        [
            {"category": "ACTION_REQUIRED", "level": "IMPORTANT", "channels": ["IN_APP"]},
            {"category": "ACTION_REQUIRED", "level": "URGENT", "channels": ["IN_APP"]},
        ]
    )
    event.payload_json = {**event.payload_json, "level": "URGENT", "template_code": "todo.created"}
    event.save(update_fields=["payload_json"])

    todo_consumer.consume(event)

    notice = Notification.objects.get(dedup_key=f"notify:{event.payload_json['dedup_key']}")
    assert notice.level == "IMPORTANT"
