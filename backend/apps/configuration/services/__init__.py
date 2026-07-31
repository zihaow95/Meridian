"""Configuration command services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationDecision
from apps.authorization.models.admin_change import AdminChangeRequest, AdminChangeStatus
from apps.authorization.services.request_admin_change import (
    AdminChangeRequestDenied,
    RequestAdminChange,
    dual_control_enabled,
)
from apps.authorization.services.review_admin_change import (
    AdminChangeReviewDenied,
    ReviewAdminChange,
)
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationSnapshot,
    ConfigurationStatus,
    ConfigurationVersion,
    compute_content_digest,
)
from apps.configuration.schema_registry import (
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    TECHNICAL_FILE_CATALOG_CODE,
    validate_content,
)
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


class ConfigurationValidationFailed(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class ConfigurationVersionNotPublishable(ValueError):
    """The version's status does not allow publishing.

    Subclasses ValueError so callers written against the previous contract keep
    working, while the API can still answer a state conflict as 409.
    """


class PublicationApprovalRequired(Exception):
    """Publishing this definition needs a second person's approval."""


class PublicationApprovalInvalid(Exception):
    """The supplied approval does not authorize publishing this version."""


class ConfigurationPublicationDenied(Exception):
    def __init__(self, decision: AuthorizationDecision) -> None:
        self.decision = decision
        super().__init__(decision.reason_code)


PUBLICATION_ACTION_TYPE = "configuration.publish"
PUBLICATION_REQUEST_ACTION = "configuration.publication.request"
PUBLICATION_REVIEW_ACTION = "configuration.publication.review"
PUBLICATION_RESOURCE_TYPE = "configuration.version"

# Definitions that govern controlled files and notifications for every user, so
# no single administrator may change them on their own.
DUAL_CONTROL_DEFINITION_CODES = frozenset(
    {
        TECHNICAL_FILE_CATALOG_CODE,
        PRODUCT_MATERIAL_REQUIREMENTS_CODE,
        NOTIFICATION_TEMPLATE_CATALOG_CODE,
        NOTIFICATION_DELIVERY_POLICY_CODE,
    }
)


def requires_dual_control(definition_code: str) -> bool:
    return definition_code in DUAL_CONTROL_DEFINITION_CODES or dual_control_enabled()


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
    approved_request: AdminChangeRequest | None = None
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        command_context = self.context or CommandContext.for_actor(self.actor)
        if self.version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
            raise ConfigurationVersionNotPublishable(
                f"Cannot publish version in status {self.version.status}"
            )
        definition_code = self.version.definition.definition_code
        if self.approved_request is None:
            if requires_dual_control(definition_code):
                raise PublicationApprovalRequired(definition_code)
        else:
            self._assert_approval_authorizes_this_version(self.approved_request)

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
                previous_published.current_published_slot = None
                previous_published.save(
                    update_fields=["status", "current_published_slot", "updated_at"]
                )

            if self.approved_request is not None:
                self.approved_request.status = AdminChangeStatus.APPLIED
                self.approved_request.save(update_fields=["status", "updated_at"])

            self.version.status = ConfigurationStatus.PUBLISHED
            self.version.current_published_slot = 1
            self.version.published_by = self.actor
            self.version.published_at = now
            self.version.diff_summary = diff_summary
            self.version.validation_errors = []
            self.version.save(
                update_fields=[
                    "status",
                    "current_published_slot",
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

    def _assert_approval_authorizes_this_version(self, request: AdminChangeRequest) -> None:
        if request.status != AdminChangeStatus.APPROVED:
            raise PublicationApprovalInvalid(f"Approval is {request.status}, not APPROVED.")
        if request.action_type != PUBLICATION_ACTION_TYPE:
            raise PublicationApprovalInvalid(
                f"Approval covers {request.action_type}, not a configuration publication."
            )
        approved_version = request.target_summary.get("version_public_id")
        if str(approved_version) != str(self.version.public_id):
            raise PublicationApprovalInvalid(
                f"Approval covers version {approved_version}, not {self.version.public_id}."
            )


@dataclass(frozen=True)
class RequestConfigurationPublication:
    """Ask a second administrator to approve publishing a configuration version."""

    context: CommandContext
    version_public_id: Any

    def execute(self) -> AdminChangeRequest:
        version = ConfigurationVersion.objects.select_related("definition").get(
            organization_id=self.context.actor.organization_id,
            public_id=self.version_public_id,
        )
        if version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
            raise ValueError(f"Cannot request publication for version in status {version.status}")

        current = (
            ConfigurationVersion.objects.filter(
                definition=version.definition,
                current_published_slot=1,
            )
            .values("version_number", "content_digest")
            .first()
        )
        try:
            return RequestAdminChange(
                context=self.context,
                action_type=PUBLICATION_ACTION_TYPE,
                target_summary={
                    "version_public_id": str(version.public_id),
                    "definition_code": version.definition.definition_code,
                    "version_number": version.version_number,
                },
                before_summary=dict(current) if current else {},
                after_summary={"content_digest": version.content_digest},
                action_code=PUBLICATION_REQUEST_ACTION,
                resource_type=PUBLICATION_RESOURCE_TYPE,
            ).execute()
        except AdminChangeRequestDenied as denied:
            raise ConfigurationPublicationDenied(denied.decision) from denied


@dataclass(frozen=True)
class ReviewConfigurationPublication:
    """Approve or reject someone else's request to publish a configuration version."""

    context: CommandContext
    request_public_id: Any
    decision: str

    def execute(self) -> AdminChangeRequest:
        request = AdminChangeRequest.objects.get(
            public_id=self.request_public_id,
            action_type=PUBLICATION_ACTION_TYPE,
        )
        review = ReviewAdminChange(
            actor=self.context.actor,
            request=request,
            context=self.context,
            action_code=PUBLICATION_REVIEW_ACTION,
            resource_type=PUBLICATION_RESOURCE_TYPE,
        )
        try:
            if self.decision == AdminChangeStatus.APPROVED:
                return review.approve()
            if self.decision == AdminChangeStatus.REJECTED:
                return review.reject()
        except AdminChangeReviewDenied as denied:
            raise ConfigurationPublicationDenied(denied.decision) from denied
        raise ValueError(f"Unsupported review decision: {self.decision}")


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
