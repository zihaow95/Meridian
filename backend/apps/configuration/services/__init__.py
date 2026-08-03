"""Configuration command services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationDecision,
    ResourceDescriptor,
)
from apps.authorization.models.admin_change import AdminChangeRequest, AdminChangeStatus
from apps.authorization.policies.engine import authorize
from apps.authorization.services.request_admin_change import (
    AdminChangeRequestDenied,
    RequestAdminChange,
    dual_control_enabled,
)
from apps.authorization.services.review_admin_change import (
    AdminChangeReviewDenied,
    ReviewAdminChange,
)
from apps.authorization.services.subject import subject_for
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
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import (
    OutboxMessage,
    register_outbox_event,
    schedule_local_dispatch_after_commit,
)


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
        command_context = self.context or CommandContext.for_actor(self.actor)
        with transaction.atomic():
            definition = (
                ConfigurationDefinition.objects.select_for_update()
                .filter(pk=self.definition.pk, organization_id=self.actor.organization_id)
                .first()
            )
            if definition is None:
                raise PermissionDeniedError()
            auth_decision = authorize(
                subject_for(self.actor),
                action="configuration.draft.create",
                resource=ResourceDescriptor(
                    resource_type="configuration.version",
                    public_id=None,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise PermissionDeniedError()
            latest = (
                ConfigurationVersion.objects.filter(definition=definition)
                .order_by("-version_number")
                .first()
            )
            next_version = 1 if latest is None else latest.version_number + 1
            version = ConfigurationVersion.objects.create(
                organization=definition.organization,
                definition=definition,
                version_number=next_version,
                status=ConfigurationStatus.DRAFT,
                content_json=self.content,
                content_digest=compute_content_digest(self.content),
                scope_json=self.scope or {},
                created_by=self.actor,
            )
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="configuration.draft.create",
                    resource_type="configuration.version",
                    resource_public_id=version.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={
                        "definition_code": definition.definition_code,
                        "version_number": version.version_number,
                    },
                )
            )
            outbox_event = register_outbox_event(
                OutboxMessage(
                    event_type="configuration.draft.created",
                    aggregate_type="configuration.version",
                    aggregate_id=version.public_id,
                    payload={
                        "definition_code": definition.definition_code,
                        "version_number": version.version_number,
                        "content_digest": version.content_digest,
                    },
                    occurred_at=command_context.occurred_at,
                )
            )
            schedule_local_dispatch_after_commit(outbox_event)
            return version


@dataclass(frozen=True)
class ValidateVersion:
    version: ConfigurationVersion
    actor: User
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        command_context = self.context or CommandContext.for_actor(self.actor)
        failed_errors: list[str] | None = None
        with transaction.atomic():
            version = (
                ConfigurationVersion.objects.select_for_update()
                .select_related("definition")
                .filter(pk=self.version.pk, organization_id=self.actor.organization_id)
                .first()
            )
            if version is None:
                raise PermissionDeniedError()
            auth_decision = authorize(
                subject_for(self.actor),
                action="configuration.draft.create",
                resource=ResourceDescriptor(
                    resource_type="configuration.version",
                    public_id=version.public_id,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise PermissionDeniedError()
            if version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
                raise ValueError(f"Cannot validate version in status {version.status}")

            errors = validate_content(version.definition.definition_code, version.content_json)
            version.status = ConfigurationStatus.VALIDATING
            version.validation_errors = errors
            if errors:
                version.status = ConfigurationStatus.FAILED
                failed_errors = errors
            version.save(update_fields=["status", "validation_errors", "updated_at"])
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="configuration.version.validate",
                    resource_type="configuration.version",
                    resource_public_id=version.public_id,
                    result=AuditResult.FAILURE if errors else AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={
                        "status": version.status,
                        "validation_errors": errors,
                    },
                )
            )
            outbox_event = register_outbox_event(
                OutboxMessage(
                    event_type="configuration.version.validated",
                    aggregate_type="configuration.version",
                    aggregate_id=version.public_id,
                    payload={
                        "status": version.status,
                        "validation_errors": errors,
                        "content_digest": version.content_digest,
                    },
                    occurred_at=command_context.occurred_at,
                )
            )
            schedule_local_dispatch_after_commit(outbox_event)
            if failed_errors is None:
                return version
        # Raise after commit so FAILED + validation_errors remain durable facts.
        raise ConfigurationValidationFailed(failed_errors)


@dataclass(frozen=True)
class PublishVersion:
    version: ConfigurationVersion
    actor: User
    approved_request: AdminChangeRequest | None = None
    context: CommandContext | None = None

    def execute(self) -> ConfigurationVersion:
        command_context = self.context or CommandContext.for_actor(self.actor)
        now = command_context.occurred_at
        failed_errors: list[str] | None = None
        with transaction.atomic():
            version = (
                ConfigurationVersion.objects.select_for_update()
                .select_related("definition")
                .get(pk=self.version.pk, organization_id=self.actor.organization_id)
            )
            auth_decision = authorize(
                subject_for(self.actor),
                action="configuration.version.publish",
                resource=ResourceDescriptor(
                    resource_type="configuration.version",
                    public_id=version.public_id,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise PermissionDeniedError()
            if version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
                raise ConfigurationVersionNotPublishable(
                    f"Cannot publish version in status {version.status}"
                )
            definition_code = version.definition.definition_code
            approved_request: AdminChangeRequest | None = None
            if self.approved_request is None:
                if requires_dual_control(definition_code):
                    raise PublicationApprovalRequired(definition_code)
            else:
                approved_request = AdminChangeRequest.objects.select_for_update().get(
                    pk=self.approved_request.pk,
                    proposed_by__organization_id=self.actor.organization_id,
                )
                self._assert_approval_authorizes_this_version(approved_request, version=version)

            errors = validate_content(definition_code, version.content_json)
            if errors:
                version.status = ConfigurationStatus.FAILED
                version.validation_errors = errors
                version.save(update_fields=["status", "validation_errors", "updated_at"])
                append_event(
                    AuditRecord(
                        actor=command_context.actor,
                        action_code="configuration.version.publish",
                        resource_type="configuration.version",
                        resource_public_id=version.public_id,
                        result=AuditResult.FAILURE,
                        trace_id=command_context.trace_id,
                        occurred_at=command_context.occurred_at,
                        acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                        after_summary={
                            "status": version.status,
                            "validation_errors": errors,
                        },
                    )
                )
                failed_errors = errors
            else:
                return self._publish_validated(
                    version=version,
                    approved_request=approved_request,
                    command_context=command_context,
                    now=now,
                )
        assert failed_errors is not None
        raise ConfigurationValidationFailed(failed_errors)

    def _publish_validated(
        self,
        *,
        version: ConfigurationVersion,
        approved_request: AdminChangeRequest | None,
        command_context: CommandContext,
        now: Any,
    ) -> ConfigurationVersion:
        previous_published = (
            ConfigurationVersion.objects.select_for_update()
            .filter(
                definition=version.definition,
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
                "new_digest": version.content_digest,
            }
            previous_published.status = ConfigurationStatus.RETIRED
            previous_published.current_published_slot = None
            previous_published.save(
                update_fields=["status", "current_published_slot", "updated_at"]
            )

        if approved_request is not None:
            if approved_request.status != AdminChangeStatus.APPROVED:
                raise PublicationApprovalInvalid(
                    f"Approval is {approved_request.status}, not APPROVED."
                )
            approved_request.status = AdminChangeStatus.APPLIED
            approved_request.save(update_fields=["status", "updated_at"])

        version.status = ConfigurationStatus.PUBLISHED
        version.current_published_slot = 1
        version.published_by = self.actor
        version.published_at = now
        version.diff_summary = diff_summary
        version.validation_errors = []
        version.save(
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
                resource_public_id=version.public_id,
                result=AuditResult.SUCCESS,
                trace_id=command_context.trace_id,
                occurred_at=command_context.occurred_at,
                acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                after_summary={
                    "definition_code": version.definition.definition_code,
                    "version_number": version.version_number,
                },
            )
        )
        register_outbox_event(
            OutboxMessage(
                event_type="configuration.published",
                aggregate_type="configuration.version",
                aggregate_id=version.public_id,
                payload={
                    "definition_code": version.definition.definition_code,
                    "version_number": version.version_number,
                    "content_digest": version.content_digest,
                },
                occurred_at=command_context.occurred_at,
            )
        )
        return version

    def _assert_approval_authorizes_this_version(
        self,
        request: AdminChangeRequest,
        *,
        version: ConfigurationVersion | None = None,
    ) -> None:
        target = version or self.version
        if request.status != AdminChangeStatus.APPROVED:
            raise PublicationApprovalInvalid(f"Approval is {request.status}, not APPROVED.")
        if request.action_type != PUBLICATION_ACTION_TYPE:
            raise PublicationApprovalInvalid(
                f"Approval covers {request.action_type}, not a configuration publication."
            )
        approved_version = request.target_summary.get("version_public_id")
        if str(approved_version) != str(target.public_id):
            raise PublicationApprovalInvalid(
                f"Approval covers version {approved_version}, not {target.public_id}."
            )


@dataclass(frozen=True)
class RequestConfigurationPublication:
    """Ask a second administrator to approve publishing a configuration version."""

    context: CommandContext
    version_public_id: Any

    def execute(self) -> AdminChangeRequest:
        with transaction.atomic():
            version = (
                ConfigurationVersion.objects.select_for_update()
                .select_related("definition")
                .get(
                    organization_id=self.context.actor.organization_id,
                    public_id=self.version_public_id,
                )
            )
            if version.status not in {ConfigurationStatus.DRAFT, ConfigurationStatus.FAILED}:
                raise ValueError(
                    f"Cannot request publication for version in status {version.status}"
                )

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
        with transaction.atomic():
            request = AdminChangeRequest.objects.select_for_update().get(
                public_id=self.request_public_id,
                action_type=PUBLICATION_ACTION_TYPE,
                proposed_by__organization_id=self.context.actor.organization_id,
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
        command_context = self.context or CommandContext.for_actor(self.actor)
        with transaction.atomic():
            version = (
                ConfigurationVersion.objects.select_for_update()
                .filter(pk=self.version.pk, organization_id=self.actor.organization_id)
                .first()
            )
            if version is None:
                raise PermissionDeniedError()
            auth_decision = authorize(
                subject_for(self.actor),
                action="configuration.version.read",
                resource=ResourceDescriptor(
                    resource_type="configuration.version",
                    public_id=version.public_id,
                    organization_id=self.actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not auth_decision.allowed:
                raise PermissionDeniedError()
            if version.status != ConfigurationStatus.PUBLISHED:
                raise ValueError("Only published configuration versions can be snapshotted.")
            snapshot = ConfigurationSnapshot.objects.create(
                organization=version.organization,
                version=version,
                content_copy=version.content_json,
                content_hash=version.content_digest,
                reference_type=self.reference_type,
                reference_id=self.reference_id,
            )
            append_event(
                AuditRecord(
                    actor=command_context.actor,
                    action_code="configuration.snapshot.create",
                    resource_type="configuration.snapshot",
                    resource_public_id=snapshot.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=command_context.trace_id,
                    occurred_at=command_context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(command_context.actor),
                    after_summary={
                        "version_public_id": str(version.public_id),
                        "reference_type": self.reference_type,
                        "reference_id": str(self.reference_id),
                        "content_hash": snapshot.content_hash,
                    },
                )
            )
            outbox_event = register_outbox_event(
                OutboxMessage(
                    event_type="configuration.snapshot.created",
                    aggregate_type="configuration.snapshot",
                    aggregate_id=snapshot.public_id,
                    payload={
                        "version_public_id": str(version.public_id),
                        "reference_type": self.reference_type,
                        "reference_id": str(self.reference_id),
                        "content_hash": snapshot.content_hash,
                    },
                    occurred_at=command_context.occurred_at,
                )
            )
            schedule_local_dispatch_after_commit(outbox_event)
            return snapshot
