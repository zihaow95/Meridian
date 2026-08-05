"""Resolve a notification's class, wording and channels from configuration.

Nothing here writes a notification. This module answers one question — given a
template code and some variables, what may be said and where may it go — and
names the exact configuration versions it read, so the answer can be replayed
after the configuration moves on.

The variable check is the reason this is a separate module: a summary is allowed
to contain only the variables its template declared. Anything else offered by a
caller is refused instead of interpolated, because "whatever the caller passed"
is how an object's body, a sensitive field or a credential ends up in a summary
that is shown outside the object's own permission check.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import (
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
)
from apps.identity.models.organization import Organization

SUMMARY_MAX_LENGTH = 512


class NotificationTemplateUnavailable(Exception):
    """No published template catalog answers for this template code."""


class NotificationPolicyUnavailable(Exception):
    """No published policy rule answers for this category and level."""


@dataclass(frozen=True)
class ResolvedNotification:
    template_code: str
    category: str
    level: str
    summary: str
    channels: tuple[str, ...]
    template_version_id: int
    policy_version_id: int
    policy_snapshot: dict[str, Any]


def _published_version(
    organization: Organization, definition_code: str
) -> ConfigurationVersion | None:
    definition = ConfigurationDefinition.objects.filter(
        organization=organization, definition_code=definition_code
    ).first()
    if definition is None:
        return None
    return (
        ConfigurationVersion.objects.filter(
            definition=definition, status=ConfigurationStatus.PUBLISHED
        )
        .order_by("-version_number")
        .first()
    )


def published_template_catalog(organization: Organization) -> ConfigurationVersion:
    version = _published_version(organization, NOTIFICATION_TEMPLATE_CATALOG_CODE)
    if version is None:
        raise NotificationTemplateUnavailable(
            "No notification template catalog is published for this organization."
        )
    return version


def published_delivery_policy(organization: Organization) -> ConfigurationVersion:
    version = _published_version(organization, NOTIFICATION_DELIVERY_POLICY_CODE)
    if version is None:
        raise NotificationPolicyUnavailable(
            "No notification delivery policy is published for this organization."
        )
    return version


def _template_entry(catalog: ConfigurationVersion, template_code: str) -> dict[str, Any]:
    for entry in catalog.content_json.get("templates", []):
        if entry.get("template_code") == template_code:
            return entry
    raise NotificationTemplateUnavailable(
        f"Template {template_code} is not in published catalog version {catalog.version_number}."
    )


def _policy_rule(policy: ConfigurationVersion, *, category: str, level: str) -> dict[str, Any]:
    for rule in policy.content_json.get("rules", []):
        if rule.get("category") == category and rule.get("level") == level:
            return rule
    raise NotificationPolicyUnavailable(
        f"Published policy version {policy.version_number} has no rule for {category}/{level}."
    )


def _template_variables(summary_template: str) -> set[str]:
    return {
        field for _, field, _, _ in string.Formatter().parse(summary_template) if field is not None
    }


def render_summary(
    *, summary_template: str, allowed_variables: list[str], variables: dict[str, Any]
) -> str:
    """Render the minimal summary, refusing anything the template did not declare."""

    allowed = set(allowed_variables)

    offered = set(variables)
    undeclared = sorted(offered - allowed)
    if undeclared:
        raise ValueError(
            "These variables are not declared by the template, so they will not be "
            f"rendered into a summary: {', '.join(undeclared)}"
        )

    referenced = _template_variables(summary_template)
    unbacked = sorted(referenced - allowed)
    if unbacked:
        raise ValueError(
            f"The template references variables it does not declare: {', '.join(unbacked)}"
        )

    missing = sorted(referenced - offered)
    if missing:
        raise ValueError(f"These declared variables have no value: {', '.join(missing)}")

    summary = summary_template.format(**{name: variables[name] for name in referenced})
    if len(summary) > SUMMARY_MAX_LENGTH:
        raise ValueError(
            f"The rendered summary is {len(summary)} characters, over the "
            f"{SUMMARY_MAX_LENGTH} a summary may occupy."
        )
    return summary


def resolve_notification(
    *,
    organization: Organization,
    template_code: str,
    variables: dict[str, Any],
) -> ResolvedNotification:
    """Decide class, wording and channels, pinning the versions that said so.

    Level is always the published template's default. Callers submit business
    facts only; overriding the class here would fork the versioned policy.
    """

    catalog = published_template_catalog(organization)
    entry = _template_entry(catalog, template_code)
    category = str(entry["category"])
    effective_level = str(entry["default_level"])

    summary = render_summary(
        summary_template=str(entry["summary_template"]),
        allowed_variables=list(entry.get("allowed_variables", [])),
        variables=variables,
    )

    policy = published_delivery_policy(organization)
    rule = _policy_rule(policy, category=category, level=effective_level)

    return ResolvedNotification(
        template_code=template_code,
        category=category,
        level=effective_level,
        summary=summary,
        channels=tuple(str(channel) for channel in rule.get("channels", [])),
        template_version_id=catalog.id,
        policy_version_id=policy.id,
        policy_snapshot=dict(rule),
    )
