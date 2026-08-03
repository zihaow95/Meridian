"""Idempotent Phase 6 acceptance fixtures for cold-start and E2E.

Builds on `seed_e2e_user`, then adds phase-6 actions, notification catalogs,
pilot accounts/batches, controlled document volume, pending triage rows, and a
bounded set of legacy baseline products. Bytes stay under FILE_STORAGE_ROOT and
must never be committed to Git.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.authorization.actions import PHASE6_ACTIONS
from apps.authorization.models.assignment import RoleAssignment, ScopeType, build_scope_key
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import (
    FILE_UPLOAD_DEFINITION_CODE,
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    TECHNICAL_FILE_CATALOG_CODE,
)
from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.management.commands.seed_e2e_user import (
    E2E_APPROVER_LOGIN_KEY,
    E2E_LOGIN_KEY,
    E2E_ORG_NAME,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.notifications.models import (
    NotificationCategory,
    NotificationLevel,
    NotificationStatus,
)
from apps.notifications.services.notifications import CreateInAppNotification
from apps.pilot.models import PilotBatchPurpose, PilotBatchStatus, PilotFeedbackSeverity
from apps.pilot.services.batches import (
    AddPilotParticipant,
    CreatePilotBatch,
    StartPilotBatch,
)
from apps.pilot.services.feedback import (
    AssignPilotFeedback,
    ClosePilotFeedback,
    OpenPilotFeedback,
    RetestPilotFeedback,
    StartFeedbackHandling,
    SubmitFeedbackRetest,
)
from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeOwnerType,
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialStatus,
    ProductAsset,
    ProductMaterial,
)
from apps.products.services.create_legacy_baseline import CreateLegacyBaselineDraft
from apps.products.services.legacy_material_intake import CreateLegacyMaterialSubmission
from apps.products.services.publish_legacy_baseline import PublishLegacyBaseline

PHASE6_ORG_PUBLIC_ID = UUID("6a6a6a6a-6b6b-6c6c-6d6d-6e6e6e6e6e6e")
PHASE6_PILOT_EMPLOYEE_NO = "P-E2E-001"
PHASE6_PILOT_PASSWORD = "phase6-pilot-secret"
PHASE6_INACTIVE_EMPLOYEE_NO = "P-E2E-INACTIVE"
PHASE6_PILOT_BATCH_NAME = "Phase6 Internal Acceptance"
PHASE6_PRODUCT_COUNT = 20
PHASE6_CONTROLLED_VERSION_COUNT = 100
PHASE6_HISTORY_VERSION_COUNT = 20
PHASE6_PENDING_TRIAGE_COUNT = 10
PHASE6_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_CATEGORY_LEVELS: tuple[tuple[str, str], ...] = (
    (NotificationCategory.ACTION_REQUIRED, NotificationLevel.URGENT),
    (NotificationCategory.DEADLINE, NotificationLevel.IMPORTANT),
    (NotificationCategory.BUSINESS_ALERT, NotificationLevel.NORMAL),
    (NotificationCategory.PROCESS_RESULT, NotificationLevel.IMPORTANT),
    (NotificationCategory.SYSTEM_FAILURE, NotificationLevel.URGENT),
    (NotificationCategory.INFORMATION, NotificationLevel.NORMAL),
)


class Command(BaseCommand):
    help = "Seed idempotent Phase 6 acceptance fixtures (safe to re-run)."

    def handle(self, *args: object, **options: object) -> None:
        call_command("seed_e2e_user")
        organization = Organization.objects.get(name=E2E_ORG_NAME)
        if organization.public_id != PHASE6_ORG_PUBLIC_ID:
            Organization.objects.filter(pk=organization.pk).update(public_id=PHASE6_ORG_PUBLIC_ID)
            organization.refresh_from_db()
        actor = User.objects.get(login_key=E2E_LOGIN_KEY, organization=organization)
        approver = User.objects.get(login_key=E2E_APPROVER_LOGIN_KEY, organization=organization)

        for action_code, resource_type, _category in PHASE6_ACTIONS:
            self._grant_action(actor, action_code, resource_type)
        self._grant_action(actor, "notification.read", "identity.user")
        self._grant_action(approver, "pilot.feedback.retest", "pilot.feedback")
        self._grant_action(approver, "pilot.feedback.close", "pilot.feedback")
        self._grant_action(approver, "configuration.publication.review", "configuration.version")

        self._publish_file_upload_limit(organization, actor)
        self._publish_technical_catalog(organization, actor)
        self._publish_material_requirements(organization, actor)
        self._publish_notification_catalogs(organization, actor)
        pilot = self._ensure_pilot_user(organization, actor)
        self._ensure_inactive_pilot_user(organization)
        batch = self._ensure_pilot_batch(actor, pilot)
        self._ensure_sample_feedback_closed(actor, approver, batch)
        versions = self._ensure_document_volume(organization, actor)
        self._ensure_pending_triage(actor, versions)
        self._ensure_legacy_products(actor, versions)
        # After products exist so ACTION_REQUIRED can deep-link a real product.
        self._ensure_notifications(actor)

        self.stdout.write(
            self.style.SUCCESS(
                "Phase 6 acceptance seed ready: "
                f"products<={PHASE6_PRODUCT_COUNT}, "
                f"controlled>={PHASE6_CONTROLLED_VERSION_COUNT}, "
                f"history>={PHASE6_HISTORY_VERSION_COUNT}, "
                f"pending>={PHASE6_PENDING_TRIAGE_COUNT}, "
                f"pilot_employee_no={PHASE6_PILOT_EMPLOYEE_NO}"
            )
        )

    def _grant_action(self, user: User, action_code: str, resource_type: str) -> None:
        action, _ = PermissionAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": ActionCategory.ADMIN,
            },
        )
        role_code = f"P6_{action_code.replace('.', '_').upper()}"
        role, _ = Role.objects.get_or_create(
            role_code=role_code,
            defaults={"name": role_code, "role_type": RoleType.PLATFORM},
        )
        RolePermission.objects.get_or_create(
            role=role,
            action=action,
            defaults={
                "max_data_level": DataSensitivityLevel.HIGHLY_SENSITIVE,
                "requires_object_scope": False,
            },
        )
        scope_id = user.organization_id
        scope_key = build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=scope_id)
        RoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            scope_key=scope_key,
            defaults={
                "scope_id": scope_id,
                "effective_from": timezone.now(),
                "configured_by": user,
                "status": "ACTIVE",
                "active_slot": 1,
            },
        )

    def _publish_config(
        self,
        *,
        organization: Organization,
        actor: User,
        definition_code: str,
        content: dict[str, Any],
    ) -> ConfigurationVersion:
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code=definition_code,
            defaults={"name": definition_code, "description": "Phase 6 acceptance"},
        )
        published = (
            ConfigurationVersion.objects.filter(
                definition=definition, status=ConfigurationStatus.PUBLISHED
            )
            .order_by("-version_number")
            .first()
        )
        if published is not None and published.content_json == content:
            return published
        ConfigurationVersion.objects.filter(
            definition=definition, status=ConfigurationStatus.PUBLISHED
        ).update(status=ConfigurationStatus.RETIRED, current_published_slot=None)
        return ConfigurationVersion.objects.create(
            organization=organization,
            definition=definition,
            version_number=ConfigurationVersion.objects.filter(definition=definition).count() + 1,
            status=ConfigurationStatus.PUBLISHED,
            current_published_slot=1,
            content_json=content,
            created_by=actor,
            published_at=timezone.now(),
        )

    def _publish_file_upload_limit(self, organization: Organization, actor: User) -> None:
        self._publish_config(
            organization=organization,
            actor=actor,
            definition_code=FILE_UPLOAD_DEFINITION_CODE,
            content={
                "allowed_mime_types": ["application/pdf", "image/png", "text/plain"],
                "max_bytes": PHASE6_MAX_UPLOAD_BYTES,
            },
        )

    def _publish_technical_catalog(self, organization: Organization, actor: User) -> None:
        self._publish_config(
            organization=organization,
            actor=actor,
            definition_code=TECHNICAL_FILE_CATALOG_CODE,
            content={
                "catalog_items": [
                    {
                        "item_code": "PRODUCT_LABEL",
                        "name": "Product label",
                        "allowed_mime_types": ["application/pdf", "text/plain", "image/png"],
                        "max_bytes": PHASE6_MAX_UPLOAD_BYTES,
                        "preview_enabled": True,
                        "default_sensitivity_level": "SENSITIVE_CONTROLLED",
                        "retention_years": 5,
                    }
                ]
            },
        )

    def _publish_material_requirements(self, organization: Organization, actor: User) -> None:
        self._publish_config(
            organization=organization,
            actor=actor,
            definition_code=PRODUCT_MATERIAL_REQUIREMENTS_CODE,
            content={
                "requirements": [
                    {
                        "product_category_code": "YOGURT",
                        "lifecycle_state": "ACTIVE",
                        "materials": [
                            {
                                "material_type_code": "PRODUCT_LABEL",
                                "requirement": "REQUIRED",
                            }
                        ],
                    }
                ]
            },
        )

    def _publish_notification_catalogs(self, organization: Organization, actor: User) -> None:
        templates = [
            {
                "template_code": "todo.created",
                "category": NotificationCategory.ACTION_REQUIRED,
                "default_level": NotificationLevel.IMPORTANT,
                "summary_template": "待办 {title} 需要处理",
                "allowed_variables": ["title"],
            },
            *[
                {
                    "template_code": f"phase6.{category.lower()}",
                    "category": category,
                    "default_level": level,
                    "summary_template": f"[{category}] {{title}}",
                    "allowed_variables": ["title"],
                }
                for category, level in _CATEGORY_LEVELS
            ],
        ]
        self._publish_config(
            organization=organization,
            actor=actor,
            definition_code=NOTIFICATION_TEMPLATE_CATALOG_CODE,
            content={"templates": templates},
        )
        rules = [
            {
                "category": NotificationCategory.ACTION_REQUIRED,
                "level": NotificationLevel.IMPORTANT,
                "channels": ["IN_APP"],
            },
            *[
                {"category": category, "level": level, "channels": ["IN_APP"]}
                for category, level in _CATEGORY_LEVELS
            ],
        ]
        # Cover every category×level cell used by the six templates.
        self._publish_config(
            organization=organization,
            actor=actor,
            definition_code=NOTIFICATION_DELIVERY_POLICY_CODE,
            content={"rules": rules},
        )

    def _ensure_pilot_user(self, organization: Organization, actor: User) -> User:
        user = User.objects.filter(
            organization=organization, employee_no=PHASE6_PILOT_EMPLOYEE_NO
        ).first()
        if user is None:
            user = User.objects.create_user(
                organization=organization,
                display_name="Phase6 Pilot",
                employee_no=PHASE6_PILOT_EMPLOYEE_NO,
                password=PHASE6_PILOT_PASSWORD,
                status=UserStatus.ACTIVE,
                activated_at=timezone.now(),
            )
        else:
            user.display_name = "Phase6 Pilot"
            user.status = UserStatus.ACTIVE
            if user.activated_at is None:
                user.activated_at = timezone.now()
            user.set_password(PHASE6_PILOT_PASSWORD)
            user.save()
        for action_code, resource_type in (
            ("pilot.feedback.create", "pilot.feedback"),
            ("pilot.feedback.read", "pilot.feedback"),
            ("pilot.batch.read", "pilot.batch"),
            ("notification.message.read", "notification.message"),
            ("notification.message.mark_read", "notification.message"),
            ("notification.message.close", "notification.message"),
            ("notification.todo.read", "notification.todo"),
        ):
            self._grant_action(user, action_code, resource_type)
        return user

    def _ensure_inactive_pilot_user(self, organization: Organization) -> None:
        user = User.objects.filter(
            organization=organization, employee_no=PHASE6_INACTIVE_EMPLOYEE_NO
        ).first()
        if user is None:
            user = User.objects.create_user(
                organization=organization,
                display_name="Phase6 Inactive Pilot",
                employee_no=PHASE6_INACTIVE_EMPLOYEE_NO,
                password=PHASE6_PILOT_PASSWORD,
                status=UserStatus.DISABLED,
            )
        else:
            user.status = UserStatus.DISABLED
            user.set_password(PHASE6_PILOT_PASSWORD)
            user.save()

    def _ensure_pilot_batch(self, actor: User, pilot: User) -> Any:
        ctx = CommandContext.for_actor(actor)
        from apps.pilot.models import PilotBatch

        batch = PilotBatch.objects.filter(
            organization_id=actor.organization_id,
            name=PHASE6_PILOT_BATCH_NAME,
        ).first()
        if batch is None:
            batch = CreatePilotBatch(
                context=ctx,
                name=PHASE6_PILOT_BATCH_NAME,
                planned_participant_count=8,
                planned_duration_days=14,
                purpose=PilotBatchPurpose.INTERNAL_ACCEPTANCE,
                data_scope_note="Phase 6 internal acceptance products and files",
                feedback_owner_note="e2e-active-user collects feedback",
                known_limits_note="No DingTalk; LAN pilot login only",
                stop_conditions_note="Unresolved P0 or credential sharing",
            ).execute()
        if batch.status == PilotBatchStatus.DRAFT:
            AddPilotParticipant(
                context=ctx,
                batch_public_id=batch.public_id,
                user_public_id=pilot.public_id,
                department_snapshot="QA",
            ).execute()
            AddPilotParticipant(
                context=ctx,
                batch_public_id=batch.public_id,
                user_public_id=actor.public_id,
                department_snapshot="Product",
            ).execute()
            batch = StartPilotBatch(context=ctx, batch_public_id=batch.public_id).execute()
        return batch

    def _ensure_sample_feedback_closed(self, actor: User, approver: User, batch: Any) -> None:
        ctx = CommandContext.for_actor(actor)
        feedback = OpenPilotFeedback(
            context=ctx,
            batch_public_id=batch.public_id,
            title="Seeded closed loop sample",
            reproduction_summary="Open pilot batch and submit feedback",
            external_key="phase6-seed-feedback-1",
        ).execute()
        if feedback.severity:
            return
        feedback = AssignPilotFeedback(
            context=ctx,
            feedback_public_id=feedback.public_id,
            severity=PilotFeedbackSeverity.P1,
            assignee_public_id=actor.public_id,
        ).execute()
        feedback = StartFeedbackHandling(
            context=ctx, feedback_public_id=feedback.public_id
        ).execute()
        feedback = SubmitFeedbackRetest(
            context=ctx,
            feedback_public_id=feedback.public_id,
            target_version="0.6.0",
        ).execute()
        retest_ctx = CommandContext.for_actor(approver)
        feedback = RetestPilotFeedback(
            context=retest_ctx,
            feedback_public_id=feedback.public_id,
            passed=True,
        ).execute()
        ClosePilotFeedback(
            context=retest_ctx,
            feedback_public_id=feedback.public_id,
        ).execute()

    def _ensure_notifications(self, actor: User) -> None:
        # Point one seeded deep link at a real product so E2E can prove realtime
        # authorization denial for a limited user on an existing target.
        first_product = (
            ProductAsset.objects.filter(organization_id=actor.organization_id)
            .order_by("id")
            .first()
        )
        product_link = (
            f"/products/{first_product.public_id}" if first_product is not None else "/todos"
        )
        from apps.notifications.models import Notification

        for category, level in _CATEGORY_LEVELS:
            template_code = f"phase6.{category.lower()}"
            deep_link = (
                product_link if category == NotificationCategory.ACTION_REQUIRED else "/todos"
            )
            dedup_key = f"phase6:notify:{category}:{level}"
            CreateInAppNotification(
                recipient=actor,
                template_code=template_code,
                variables={"title": f"{category}-{level}"},
                object_type="identity.user",
                object_id=actor.public_id,
                dedup_key=dedup_key,
                deep_link=deep_link,
                action_code="notification.read",
                level=level,
            ).execute()
            existing = Notification.objects.filter(recipient=actor, dedup_key=dedup_key).first()
            if existing is None:
                continue
            if existing.status == NotificationStatus.CLOSED:
                # Never reopen CLOSED history. Seed a sibling unread fixture
                # with a stable secondary key for later E2E suites.
                reseed_key = f"{dedup_key}:open"
                CreateInAppNotification(
                    recipient=actor,
                    template_code=template_code,
                    variables={"title": f"{category}-{level}"},
                    object_type="identity.user",
                    object_id=actor.public_id,
                    dedup_key=reseed_key,
                    deep_link=deep_link,
                    action_code="notification.read",
                    level=level,
                ).execute()
                Notification.objects.filter(recipient=actor, dedup_key=reseed_key).exclude(
                    status=NotificationStatus.CLOSED
                ).update(deep_link=deep_link)
            else:
                # Refresh deep links on open rows only; keep read/close facts.
                Notification.objects.filter(pk=existing.pk).exclude(
                    status=NotificationStatus.CLOSED
                ).update(deep_link=deep_link)

    def _ensure_document_volume(
        self, organization: Organization, actor: User
    ) -> list[DocumentVersion]:
        """Create tiny controlled + history versions under storage root (not Git)."""

        from django.conf import settings

        storage_root = settings.FILE_STORAGE_ROOT
        storage_root.mkdir(parents=True, exist_ok=True)
        versions: list[DocumentVersion] = []
        now = timezone.now()

        # 100 controlled current versions across 100 documents.
        for index in range(1, PHASE6_CONTROLLED_VERSION_COUNT + 1):
            code = f"P6-DOC-{index:04d}"
            document, _ = Document.objects.get_or_create(
                organization=organization,
                document_code=code,
                defaults={
                    "title": f"Phase6 controlled {index}",
                    "source": DocumentSource.PRODUCT,
                },
            )
            payload = f"phase6-controlled-{index}".encode()
            digest = hashlib.sha256(payload).hexdigest()
            object_key = f"phase6/{code}/v1.bin"
            file_object, created = FileObject.objects.get_or_create(
                organization=organization,
                object_key=object_key,
                defaults={
                    "storage_backend": StorageBackend.NAS_NFS,
                    "size_bytes": len(payload),
                    "sha256": digest,
                    "detected_mime_type": "text/plain",
                    "storage_status": StorageStatus.ACTIVE,
                },
            )
            if created:
                path = storage_root / object_key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            version, _ = DocumentVersion.objects.get_or_create(
                organization=organization,
                document=document,
                version_number=1,
                defaults={
                    "file_object": file_object,
                    "original_filename": f"{code}.txt",
                    "declared_mime_type": "text/plain",
                    "detected_mime_type": "text/plain",
                    "status": VersionStatus.CONTROLLED,
                    "uploaded_by": actor,
                    "uploaded_at": now,
                },
            )
            if document.current_version_id != version.id:
                document.current_version = version
                document.save(update_fields=["current_version"])
            versions.append(version)

        # Promote a newer controlled version on the first 20 docs so v1 remains
        # a trusted historical (non-current) controlled version.
        for index in range(1, PHASE6_HISTORY_VERSION_COUNT + 1):
            code = f"P6-DOC-{index:04d}"
            document = Document.objects.get(organization=organization, document_code=code)
            payload = f"phase6-current-{index}".encode()
            digest = hashlib.sha256(payload).hexdigest()
            object_key = f"phase6/{code}/v2.bin"
            file_object, created = FileObject.objects.get_or_create(
                organization=organization,
                object_key=object_key,
                defaults={
                    "storage_backend": StorageBackend.NAS_NFS,
                    "size_bytes": len(payload),
                    "sha256": digest,
                    "detected_mime_type": "text/plain",
                    "storage_status": StorageStatus.ACTIVE,
                },
            )
            if created:
                path = storage_root / object_key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            version2, _ = DocumentVersion.objects.get_or_create(
                organization=organization,
                document=document,
                version_number=2,
                defaults={
                    "file_object": file_object,
                    "original_filename": f"{code}-v2.txt",
                    "declared_mime_type": "text/plain",
                    "detected_mime_type": "text/plain",
                    "status": VersionStatus.CONTROLLED,
                    "uploaded_by": actor,
                    "uploaded_at": now,
                },
            )
            if document.current_version_id != version2.id:
                document.current_version = version2
                document.save(update_fields=["current_version"])

        return versions

    def _ensure_pending_triage(self, actor: User, versions: list[DocumentVersion]) -> None:
        ctx = CommandContext.for_actor(actor)
        for index in range(PHASE6_PENDING_TRIAGE_COUNT):
            version = versions[index]
            CreateLegacyMaterialSubmission(
                context=ctx,
                document_version_public_id=version.public_id,
                owner_type="organization",
                owner_id=actor.organization_id,
                idempotency_key=f"phase6-pending-{index + 1:02d}",
                source_note=f"Phase6 pending triage {index + 1}",
            ).execute()

    def _ensure_legacy_products(self, actor: User, versions: list[DocumentVersion]) -> None:
        ctx = CommandContext.for_actor(actor)
        for index in range(1, PHASE6_PRODUCT_COUNT + 1):
            business_no = f"P6-PRD-{index:04d}"
            idem = f"phase6-product-{index:04d}"
            existing = ProductAsset.objects.filter(
                organization_id=actor.organization_id, business_no=business_no
            ).first()
            if existing is not None:
                continue
            draft = CreateLegacyBaselineDraft(
                context=ctx,
                payload={
                    "name": f"Phase6 Acceptance {index}",
                    "category_code": "YOGURT",
                    "brand_code": "MERIDIAN",
                    "business_no": business_no,
                    "specification": f"{100 + index}g",
                    "sku_code": f"SKU-P6-{index:04d}",
                    "barcode": f"69100000{index:05d}",
                },
                idempotency_key=idem,
            ).execute()
            version = versions[(index - 1) % len(versions)]
            material = ProductMaterial.objects.create(
                organization_id=actor.organization_id,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=draft.product.id,
                material_type_code="PRODUCT_LABEL",
                document_version=version,
                sensitivity_level=version.sensitivity_level or "INTERNAL",
                material_status=MaterialStatus.APPROVED,
                version_no=1,
                current_slot=1,
            )
            MaterialConfirmation.objects.create(
                organization_id=actor.organization_id,
                material=material,
                document_version=version,
                content_hash=version.file_object.sha256,
                requested_by=actor,
                requested_at=timezone.now(),
                confirmer=actor,
                decision=MaterialConfirmationDecision.APPROVED,
                decided_at=timezone.now(),
                live_slot=1,
            )
            PublishLegacyBaseline(
                context=ctx,
                baseline_public_id=draft.change_set.public_id,
                idempotency_key=f"{idem}-publish",
            ).execute()
