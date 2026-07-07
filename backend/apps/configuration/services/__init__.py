"""Configuration command services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationSnapshot,
    ConfigurationStatus,
    ConfigurationVersion,
    compute_content_digest,
)
from apps.configuration.schema_registry import validate_content
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class ConfigurationValidationFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class CreateDraft:
    actor: User
    definition: ConfigurationDefinition
    content: dict[str, Any]
    scope: dict[str, Any] | None = None
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        latest = (
            ConfigurationVersion.objects.filter(definition=self.definition)
            .order_by("-version_number")
            .first()
        )
        next_version = 1 if latest is None else latest.version_number + 1
        return ConfigurationVersion.objects.create(
            organization=self.definition.organization,
            definition=self.definition,
            version_number=next_version,
            status=ConfigurationStatus.DRAFT,
            content_json=self.content,
            content_digest=compute_content_digest(self.content),
            scope_json=self.scope or {},
            created_by=self.actor,
        )


@dataclass(frozen=True)
class ValidateVersion:
    version: ConfigurationVersion
    actor: User
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        if self.version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
            raise ValueError(f"Cannot validate version in status {self.version.status}")

        errors = validate_content(
            self.version.definition.definition_code, self.version.content_json
        )
        self.version.status = ConfigurationStatus.VALIDATING
        self.version.validation_errors = errors
        if errors:
            self.version.status = ConfigurationStatus.FAILED
        self.version.save(update_fields=["status", "validation_errors", "updated_at"])
        if errors:
            raise ConfigurationValidationFailed(errors)
        return self.version


@dataclass(frozen=True)
class PublishVersion:
    version: ConfigurationVersion
    actor: User
    business_confirmed: bool = True
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        command_context = self.context or CommandContext.for_actor(self.actor)
        if self.version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
            raise ValueError(f"Cannot publish version in status {self.version.status}")
        if not self.business_confirmed:
            raise ValueError("Business confirmation is required to publish configuration.")

        errors = validate_content(
            self.version.definition.definition_code, self.version.content_json
        )
        if errors:
            self.version.status = ConfigurationStatus.FAILED
            self.version.validation_errors = errors
            self.version.save(update_fields=["status", "validation_errors", "updated_at"])
            raise ConfigurationValidationFailed(errors)

        previous_published = (
            ConfigurationVersion.objects.filter(
                definition=self.version.definition,
                status=ConfigurationStatus.PUBLISHED,
            )
            .order_by("-version_number")
            .first()
        )
        diff_summary: dict[str, Any] = {}
        if previous_published is not None:
            diff_summary = {
                "previous_version_number": previous_published.version_number,
                "previous_digest": previous_published.content_digest,
                "new_digest": self.version.content_digest,
            }

        now = command_context.occurred_at
        with transaction.atomic():
            if previous_published is not None:
                previous_published.status = ConfigurationStatus.RETIRED
                previous_published.save(update_fields=["status", "updated_at"])

            self.version.status = ConfigurationStatus.PUBLISHED
            self.version.published_by = self.actor
            self.version.published_at = now
            self.version.diff_summary = diff_summary
            self.version.validation_errors = []
            self.version.save(
                update_fields=[
                    "status",
                    "published_by",
                    "published_at",
                    "diff_summary",
                    "validation_errors",
                    "updated_at",
                ]
            )

            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="configuration.version.publish",
                    resource_type="configuration.version",
                    resource_public_id=self.version.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={
                        "definition_code": self.version.definition.definition_code,
                        "version_number": self.version.version_number,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="configuration.published",
                    aggregate_type="configuration.version",
                    aggregate_id=self.version.public_id,
                    payload={
                        "definition_code": self.version.definition.definition_code,
                        "version_number": self.version.version_number,
                        "content_digest": self.version.content_digest,
                    },
                    occurred_at=command_context.occurred_at,
                )
            )

        return self.version


@dataclass(frozen=True)
class CreateSnapshot:
    version: ConfigurationVersion
    reference_type: str
    reference_id: Any
    actor: User
    context: CommandContext | None = None

    def execute(self) -> ConfigurationSnapshot:
        if self.version.status != ConfigurationStatus.PUBLISHED:
            raise ValueError("Only published configuration versions can be snapshotted.")
        return ConfigurationSnapshot.objects.create(
            organization=self.version.organization,
            version=self.version,
            content_copy=self.version.content_json,
            content_hash=self.version.content_digest,
            reference_type=self.reference_type,
            reference_id=self.reference_id,
        )
