"""Configure operating data sources with locked published ConfigurationVersion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
)
from apps.configuration.schema_registry import OPERATING_SOURCE_MAPPING_CODE, validate_content
from apps.configuration.services import (
    ConfigurationValidationFailed,
    CreateDraft,
    PublishVersion,
    ValidateVersion,
)
from apps.identity.models.department import Department
from apps.integrations.models import DataSource, DataSourceStatus, DataSourceType
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event

_FORBIDDEN_CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "password",
        "secret",
        "token",
        "credentials",
        "credential",
    }
)


def assert_active_for_ingestion(source: DataSource) -> None:
    if source.status != DataSourceStatus.ACTIVE:
        raise ValidationFailedError(
            message="INACTIVE data source cannot create ingestion batches."
        )
    if source.configuration_version.status != ConfigurationStatus.PUBLISHED:
        raise ValidationFailedError(
            message="Data source configuration version must be published."
        )


def _contains_forbidden_keys(content: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                full = f"{path}.{key}" if path else key
                if key.lower() in _FORBIDDEN_CREDENTIAL_KEYS:
                    found.append(full)
                _walk(value, full)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")

    _walk(content, "")
    return found


def _get_or_create_definition(*, organization_id: int, name: str) -> ConfigurationDefinition:
    definition, _ = ConfigurationDefinition.objects.get_or_create(
        organization_id=organization_id,
        definition_code=OPERATING_SOURCE_MAPPING_CODE,
        defaults={"name": name, "description": "Operating data source mapping"},
    )
    return definition


@dataclass
class ConfigureOperatingDataSource:
    context: CommandContext
    source_code: str
    name: str
    source_type: str
    owner_department_public_id: UUID
    sensitivity_level: str
    mapping_content: dict[str, Any]
    status: str = DataSourceStatus.ACTIVE

    def execute(self) -> DataSource:
        actor = self.context.actor
        now = self.context.occurred_at
        content = dict(self.mapping_content)

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="data_source.configure",
                resource=ResourceDescriptor(
                    resource_type="data_source",
                    public_id=None,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if self.source_type not in DataSourceType.values:
                raise ValidationFailedError(message=f"Unknown source_type: {self.source_type}")
            if self.status not in DataSourceStatus.values:
                raise ValidationFailedError(message=f"Unknown status: {self.status}")

            forbidden = _contains_forbidden_keys(content)
            if forbidden:
                raise ValidationFailedError(
                    message="Credentials must not enter configuration content.",
                    details={"forbidden_keys": forbidden},
                )

            schema_errors = validate_content(OPERATING_SOURCE_MAPPING_CODE, content)
            if schema_errors:
                raise ValidationFailedError(
                    message="Mapping content failed schema validation.",
                    details={"errors": schema_errors},
                )

            department = Department.objects.filter(
                public_id=self.owner_department_public_id,
                organization_id=actor.organization_id,
            ).first()
            if department is None:
                raise PermissionDeniedError()

            definition = _get_or_create_definition(
                organization_id=actor.organization_id,
                name="Operating source mapping",
            )
            draft = CreateDraft(
                actor=actor,
                definition=definition,
                content=content,
                scope={"source_code": self.source_code},
                context=self.context,
            ).execute()
            try:
                ValidateVersion(version=draft, actor=actor, context=self.context).execute()
            except ConfigurationValidationFailed as exc:
                raise ValidationFailedError(
                    message="Mapping content failed validation.",
                    details={"errors": exc.errors},
                ) from exc

            # ValidateVersion leaves VALIDATING; PublishVersion accepts DRAFT/FAILED only.
            draft.refresh_from_db()
            if draft.status == ConfigurationStatus.VALIDATING:
                draft.status = ConfigurationStatus.DRAFT
                draft.save(update_fields=["status", "updated_at"])

            published = PublishVersion(
                version=draft,
                actor=actor,
                context=self.context,
            ).execute()
            if published.status != ConfigurationStatus.PUBLISHED:
                raise ValidationFailedError(message="Configuration version must be published.")

            source, _created = DataSource.objects.update_or_create(
                organization_id=actor.organization_id,
                source_code=self.source_code,
                defaults={
                    "name": self.name,
                    "source_type": self.source_type,
                    "owner_department": department,
                    "sensitivity_level": self.sensitivity_level,
                    "status": self.status,
                    "configuration_version": published,
                },
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="data_source.configure",
                    resource_type="data_source",
                    resource_public_id=source.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "source_code": source.source_code,
                        "source_type": source.source_type,
                        "status": source.status,
                        "configuration_version_public_id": str(published.public_id),
                        "configuration_version_number": published.version_number,
                        "source_priority": published.content_json.get("source_priority"),
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="data_source.configured",
                    aggregate_type="data_source",
                    aggregate_id=source.public_id,
                    payload={
                        "source_code": source.source_code,
                        "configuration_version_public_id": str(published.public_id),
                        "status": source.status,
                    },
                    occurred_at=now,
                )
            )
            return source
