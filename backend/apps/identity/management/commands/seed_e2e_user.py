"""Seed deterministic fixtures for E2E and local smoke runs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

if TYPE_CHECKING:
    from apps.projects.models import Project
    from apps.stage_gates.models import StageGateInstance

from apps.authorization.models.assignment import RoleAssignment, ScopeType
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
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.notifications.models import Todo, TodoStatus
from apps.opportunities.services.configuration import OPPORTUNITY_RULE_DEFINITION_CODE

E2E_LOGIN_KEY = "e2e-active-user"
E2E_APPROVER_LOGIN_KEY = "e2e-approver-user"
E2E_LIMITED_LOGIN_KEY = "e2e-limited-user"
E2E_ORG_NAME = "E2E Organization"
E2E_LAUNCH_BUSINESS_NO = "E2E-LAUNCH"
E2E_REPAIR_BUSINESS_NO = "E2E-REPAIR"
E2E_REPAIR_RETRY_BUSINESS_NO = "E2E-REPAIR-RETRY"

_PHASE2_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("opportunity.create", "opportunity", "PROPOSER"),
    ("opportunity.edit", "opportunity", "PROPOSER"),
    ("opportunity.submit", "opportunity", "PROPOSER"),
    ("opportunity.full.read", "opportunity", "PRODUCT_MANAGER"),
    ("major_gate.management_conclusion.record", "stage_gate", "BOSS"),
    ("major_gate.final_decision.record", "stage_gate", "BOSS"),
    ("candidate.leadership.assign", "project_candidate", "PRODUCT_DIRECTOR"),
    ("candidate.assessment.edit", "project_candidate", "PRODUCT_DIRECTOR"),
    ("candidate.submit_review", "project_candidate", "PRODUCT_DIRECTOR"),
)

_PHASE3_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("product.search", "product", "PRODUCT_DIRECTOR"),
    ("product.read_basic", "product", "PRODUCT_DIRECTOR"),
    ("product.read_sensitive", "product", "PRODUCT_DIRECTOR"),
    ("product_draft.create", "product_change_set", "PRODUCT_DIRECTOR"),
    ("product_draft.edit_group", "product_change_set", "PRODUCT_DIRECTOR"),
    ("product_draft.submit", "product_change_set", "PRODUCT_DIRECTOR"),
    ("product_change_set.approve", "product_change_set", "PRODUCT_DIRECTOR"),
    ("attribute_group.confirm", "product_change_set", "PRODUCT_DIRECTOR"),
    ("attribute_group.return", "product_change_set", "PRODUCT_DIRECTOR"),
    ("product.publish_new", "product", "PRODUCT_DIRECTOR"),
    ("product.publish_iteration", "product", "PRODUCT_DIRECTOR"),
    ("migration.upload", "migration", "PRODUCT_DIRECTOR"),
    ("migration.review", "migration", "PRODUCT_DIRECTOR"),
    ("migration.confirm", "migration", "PRODUCT_DIRECTOR"),
    ("product.publish_baseline", "product", "PRODUCT_DIRECTOR"),
    ("external_binding.manage", "product", "PRODUCT_DIRECTOR"),
)

# The active user holds the management-committee conclusion permission only.
# FIRST_LAUNCH separation of duties requires the final decision to be recorded
# by a *different* actor (the approver), so `first_launch.final_decision.record`
# is intentionally NOT granted here.
_PHASE4_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("project_migration.confirm", "project", "PRODUCT_DIRECTOR"),
    ("first_launch.management_conclusion.record", "stage_gate", "MANAGEMENT_COMMITTEE"),
    ("emergency_execution.create", "project", "PRODUCT_DIRECTOR"),
    ("emergency_execution.complete", "project", "PRODUCT_DIRECTOR"),
    ("project.publish_repair", "project", "PRODUCT_DIRECTOR"),
    ("plan_change.apply_minor", "project", "PRODUCT_DIRECTOR"),
    ("plan_change.confirm_important", "project", "PRODUCT_DIRECTOR"),
    ("task.create", "project", "PRODUCT_DIRECTOR"),
    ("deliverable.create", "project", "PRODUCT_DIRECTOR"),
)


class Command(BaseCommand):
    help = "Create or refresh the deterministic E2E active user, permissions, and sample todo."

    def handle(self, *args: object, **options: object) -> None:
        organization, _ = Organization.objects.get_or_create(name=E2E_ORG_NAME)
        user, created = User.objects.get_or_create(
            login_key=E2E_LOGIN_KEY,
            defaults={
                "organization": organization,
                "display_name": "E2E Active User",
                "status": UserStatus.ACTIVE,
                "activated_at": timezone.now(),
            },
        )
        if not created:
            user.organization = organization
            user.display_name = "E2E Active User"
            user.status = UserStatus.ACTIVE
            user.activated_at = timezone.now()
            user.save(update_fields=["organization", "display_name", "status", "activated_at"])

        self._grant_action(user, "notification.todo.read", "notification.todo")
        self._grant_action(user, "configuration.version.read", "configuration.version")
        for action_code, resource_type, role_code in _PHASE2_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        for action_code, resource_type, role_code in _PHASE3_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        for action_code, resource_type, role_code in _PHASE4_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        self._publish_opportunity_rules(organization, user)
        self._publish_product_schema(organization)
        self._publish_project_template(organization, user)
        self._ensure_approver(organization)
        self._ensure_limited_user(organization)
        self._ensure_phase4_projects(organization, user)

        source_id = uuid4()
        Todo.objects.update_or_create(
            assignee=user,
            dedup_key="e2e:todo",
            defaults={
                "organization": organization,
                "todo_type": "review",
                "source_type": "identity.user",
                "source_id": source_id,
                "action_code": "identity.user.review",
                "status": TodoStatus.OPEN,
                "deep_link": "/admin/audit",
                "title": "E2E Todo",
            },
        )

        self.stdout.write(self.style.SUCCESS(f"E2E user ready: login_key={E2E_LOGIN_KEY}"))
        self.stdout.write(
            self.style.SUCCESS(f"E2E approver ready: login_key={E2E_APPROVER_LOGIN_KEY}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"E2E limited ready: login_key={E2E_LIMITED_LOGIN_KEY}")
        )

    def _ensure_limited_user(self, organization: Organization) -> None:
        limited, created = User.objects.get_or_create(
            login_key=E2E_LIMITED_LOGIN_KEY,
            defaults={
                "organization": organization,
                "display_name": "E2E Limited User",
                "status": UserStatus.ACTIVE,
                "activated_at": timezone.now(),
            },
        )
        if not created:
            limited.organization = organization
            limited.display_name = "E2E Limited User"
            limited.status = UserStatus.ACTIVE
            limited.activated_at = timezone.now()
            limited.save(update_fields=["organization", "display_name", "status", "activated_at"])
        self._grant_action(limited, "notification.todo.read", "notification.todo")

    def _ensure_approver(self, organization: Organization) -> None:
        approver, created = User.objects.get_or_create(
            login_key=E2E_APPROVER_LOGIN_KEY,
            defaults={
                "organization": organization,
                "display_name": "E2E Approver",
                "status": UserStatus.ACTIVE,
                "activated_at": timezone.now(),
            },
        )
        if not created:
            approver.organization = organization
            approver.display_name = "E2E Approver"
            approver.status = UserStatus.ACTIVE
            approver.activated_at = timezone.now()
            approver.save(update_fields=["organization", "display_name", "status", "activated_at"])
        for action_code, resource_type, role_code in (
            ("product.read_basic", "product", "PRODUCT_DIRECTOR"),
            ("product_change_set.approve", "product_change_set", "PRODUCT_DIRECTOR"),
            ("product.publish_iteration", "product", "PRODUCT_DIRECTOR"),
            ("product.publish_new", "product", "PRODUCT_DIRECTOR"),
            ("attribute_group.confirm", "product_change_set", "PRODUCT_DIRECTOR"),
            ("attribute_group.return", "product_change_set", "PRODUCT_DIRECTOR"),
            # FIRST_LAUNCH final decision is recorded by the approver (boss),
            # a distinct actor from the management-committee conclusion author.
            ("first_launch.final_decision.record", "stage_gate", "BOSS"),
        ):
            self._grant_action(approver, action_code, resource_type, role_code=role_code)

    def _grant_action(
        self,
        user: User,
        action_code: str,
        resource_type: str,
        *,
        role_code: str | None = None,
    ) -> None:
        action, _ = PermissionAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": ActionCategory.READ,
            },
        )
        code = role_code or f"E2E_{action_code.replace('.', '_').upper()}"
        role, _ = Role.objects.get_or_create(
            role_code=code,
            defaults={
                "name": f"E2E {action_code}",
                "role_type": RoleType.PLATFORM,
            },
        )
        RolePermission.objects.get_or_create(
            role=role,
            action=action,
            defaults={
                "max_data_level": DataSensitivityLevel.INTERNAL,
                "requires_object_scope": False,
            },
        )
        RoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "scope_type": ScopeType.ORGANIZATION,
                "effective_from": timezone.now(),
                "configured_by": user,
            },
        )

    def _publish_opportunity_rules(self, organization: Organization, actor: User) -> None:
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
            defaults={"name": "Proposal rules"},
        )
        content = {
            "member_limit": 8,
            "eligible_proposer_roles": ["PROPOSER"],
            "management_conclusion_roles": ["MANAGEMENT_COMMITTEE", "BOSS"],
            "final_decision_roles": ["BOSS"],
            "product_manager_roles": ["PRODUCT_MANAGER"],
            "case_leadership_roles": ["PRODUCT_DIRECTOR"],
            "quota_enforcement_mode": "WARN",
            "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
        }
        existing = ConfigurationVersion.objects.filter(
            organization=organization,
            definition=definition,
            version_number=1,
        ).first()
        if existing is not None:
            if existing.status == ConfigurationStatus.PUBLISHED:
                return
            existing.content_json = content
            existing.save(update_fields=["content_json", "updated_at"])
            return
        ConfigurationVersion.objects.create(
            organization=organization,
            definition=definition,
            version_number=1,
            status=ConfigurationStatus.PUBLISHED,
            content_json=content,
            created_by=actor,
            published_by=actor,
            published_at=timezone.now(),
        )

    def _publish_product_schema(self, organization: Organization) -> None:
        from apps.products.models import (
            AttributeDefinition,
            AttributeFieldType,
            AttributeGroupDefinition,
            AttributeOwnerLevel,
            AttributeSchemaStatus,
            AttributeSchemaVersion,
        )

        schema_version, created = AttributeSchemaVersion.objects.get_or_create(
            organization=organization,
            schema_code="PRODUCT_PROFILE",
            version_number=1,
            category_code="YOGURT",
            defaults={
                "status": AttributeSchemaStatus.PUBLISHED,
                "published_at": timezone.now(),
            },
        )
        if not created and schema_version.status != AttributeSchemaStatus.PUBLISHED:
            schema_version.status = AttributeSchemaStatus.PUBLISHED
            schema_version.published_at = timezone.now()
            schema_version.save(update_fields=["status", "published_at", "updated_at"])

        product_definition, created_group = AttributeGroupDefinition.objects.get_or_create(
            organization=organization,
            schema_version=schema_version,
            group_code="PRODUCT_DEFINITION",
            defaults={
                "name": "Product definition",
                "owner_level": AttributeOwnerLevel.PRODUCT,
                "display_order": 1,
                "requires_confirmation": True,
            },
        )
        if not created_group and not product_definition.requires_confirmation:
            product_definition.requires_confirmation = True
            product_definition.save(update_fields=["requires_confirmation", "updated_at"])
        AttributeDefinition.objects.get_or_create(
            organization=organization,
            group_definition=product_definition,
            field_code="core_selling_points",
            defaults={
                "field_name": "Core selling points",
                "field_type": AttributeFieldType.TEXT,
                "display_order": 1,
            },
        )
        AttributeDefinition.objects.get_or_create(
            organization=organization,
            group_definition=product_definition,
            field_code="formula_summary",
            defaults={
                "field_name": "Formula summary",
                "field_type": AttributeFieldType.TEXT,
                "sensitivity_level": "SENSITIVE_CONTROLLED",
                "display_order": 2,
            },
        )

    def _publish_project_template(self, organization: Organization, actor: User) -> None:
        import hashlib
        import json
        from pathlib import Path

        from apps.identity.models.department import Department, DepartmentStatus

        now = timezone.now()
        for code in ("PRODUCT", "RD", "OPS"):
            Department.objects.get_or_create(
                organization=organization,
                department_code=code,
                defaults={
                    "name": f"{code} Department",
                    "status": DepartmentStatus.ACTIVE,
                    "valid_from": now,
                },
            )

        seed_path = (
            Path(__file__).resolve().parents[3]
            / "configuration"
            / "defaults"
            / "project_template_v1.json"
        )
        content = json.loads(seed_path.read_text(encoding="utf-8"))
        # Derive the digest from canonical content so any template change (new
        # tasks/deliverables/stages) mints a new immutable version automatically,
        # instead of relying on a hand-maintained constant that can go stale.
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        desired_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code="PROJECT_EXECUTION_TEMPLATE",
            defaults={"name": "Project execution template"},
        )
        latest = (
            ConfigurationVersion.objects.filter(
                organization=organization,
                definition=definition,
            )
            .order_by("-version_number")
            .first()
        )
        if latest is not None and latest.status == ConfigurationStatus.PUBLISHED:
            tasks = (latest.content_json or {}).get("tasks") or []
            deliverables = (latest.content_json or {}).get("deliverables") or []
            if latest.content_digest == desired_digest and tasks and deliverables:
                return
            # Published rows are immutable — mint the next version.
            next_number = latest.version_number + 1
        elif latest is not None and latest.status != ConfigurationStatus.PUBLISHED:
            # Safe to refresh an unpublished draft in place, then publish it.
            latest.content_json = content
            latest.content_digest = desired_digest
            latest.status = ConfigurationStatus.PUBLISHED
            latest.published_by = actor
            latest.published_at = timezone.now()
            latest.save(
                update_fields=[
                    "content_json",
                    "content_digest",
                    "status",
                    "published_by",
                    "published_at",
                    "updated_at",
                ]
            )
            return
        else:
            next_number = 1

        ConfigurationVersion.objects.create(
            organization=organization,
            definition=definition,
            version_number=next_number,
            status=ConfigurationStatus.PUBLISHED,
            content_json=content,
            content_digest=desired_digest,
            created_by=actor,
            published_by=actor,
            published_at=timezone.now(),
        )

    def _ensure_phase4_projects(self, organization: Organization, leader: User) -> None:
        self._ensure_launch_project(
            organization,
            leader,
            business_no=E2E_LAUNCH_BUSINESS_NO,
            name="E2E Launch Ready",
            publishable=True,
        )
        self._ensure_launch_project(
            organization,
            leader,
            business_no=E2E_REPAIR_BUSINESS_NO,
            name="E2E Repair Pending",
            publishable=False,
        )
        self._ensure_repair_retry_project(organization, leader)

    def _ensure_repair_retry_project(self, organization: Organization, leader: User) -> None:
        """Seed a project already in PUBLISH_PENDING_REPAIR with a repaired scope.

        Its FIRST_LAUNCH final decision is already recorded by two distinct
        actors (management by the active user, final by the approver), and no
        product version exists yet, so the E2E repair button can retry publish
        with the original decision and reach OPERATING with a single version.
        """

        from apps.platform.application.command import CommandContext
        from apps.products.models import (
            ChangeSetStatus,
            ChangeSetType,
            ProductAsset,
            ProductChangeSet,
            ProductLifecycleStatus,
            ProductSourceType,
        )
        from apps.projects.models import Project, ProjectStatus, ProjectType
        from apps.projects.services.initialize_runtime import InitializeProjectRuntime
        from apps.stage_gates.models import GateResult
        from apps.stage_gates.services.record_first_launch_decision import (
            RecordFirstLaunchFinalDecision,
            RecordFirstLaunchManagementConclusion,
        )

        business_no = E2E_REPAIR_RETRY_BUSINESS_NO
        approver = User.objects.filter(login_key=E2E_APPROVER_LOGIN_KEY).first()
        if approver is None:
            raise CommandError("Approver must be seeded before the repair-retry project.")

        project = Project.objects.filter(organization=organization, business_no=business_no).first()
        if project is not None:
            from apps.stage_gates.models import MajorGateDecision

            has_final = (
                MajorGateDecision.objects.filter(
                    stage_gate__project=project,
                    stage_gate__stage_code="FIRST_LAUNCH",
                )
                .exclude(final_decision="")
                .exists()
            )
            if has_final:
                # Re-arm so every E2E run starts in PUBLISH_PENDING_REPAIR with a
                # repaired, publishable draft and no product version yet.
                self._rearm_repair_retry_project(project, business_no=business_no)
                return
            # Incomplete prior seed: tear nothing, fall through after ensuring
            # the project/draft exist for the real failure path below.
            if project.product_draft is None:
                raise CommandError("Repair-retry project is missing its product draft.")
            # Keep the draft empty so the real publish still fails closed.
            incomplete_draft = project.product_draft
            incomplete_draft.change_scope = {
                "effective_from": timezone.now().isoformat(),
                "skus": [],
                "channels": [],
            }
            incomplete_draft.status = ChangeSetStatus.APPROVED
            incomplete_draft.save(update_fields=["change_scope", "status", "updated_at"])
            project.status = ProjectStatus.ACTIVE
            project.save(update_fields=["status", "updated_at"])

        else:
            product = ProductAsset.objects.create(
                organization=organization,
                business_no=f"{business_no}-PRD",
                name="E2E Repair Retry",
                brand_code="BRAND-A",
                category_code="YOGURT",
                source_type=ProductSourceType.NEW_PROJECT,
                lifecycle_status=ProductLifecycleStatus.DEVELOPING,
                product_owner=leader,
            )
            draft = ProductChangeSet.objects.create(
                organization=organization,
                change_type=ChangeSetType.NEW_PRODUCT,
                status=ChangeSetStatus.APPROVED,
                product=product,
                target_product_asset=product,
                title="E2E Repair Retry draft",
                # Deliberately empty scope so the *first* real publish fails and
                # the project enters PUBLISH_PENDING_REPAIR organically.
                change_scope={
                    "effective_from": timezone.now().isoformat(),
                    "skus": [],
                    "channels": [],
                },
                approved_by=leader,
                created_by=leader,
            )
            project = Project.objects.create(
                organization=organization,
                business_no=business_no,
                name="E2E Repair Retry",
                project_type=ProjectType.NEW_PRODUCT,
                status=ProjectStatus.INITIALIZING,
                leader=leader,
                product_asset=product,
                product_draft=draft,
                idempotency_key=f"e2e-seed-{business_no}",
            )
            product.source_project = project
            product.save(update_fields=["source_project", "updated_at"])
            InitializeProjectRuntime(
                context=CommandContext.for_actor(leader),
                project=project,
            ).execute()
            project.refresh_from_db()

        gate = self._submit_first_launch_gate(project, submitter=leader)

        # Drive the real FIRST_LAUNCH dual-actor decision. The final decision
        # triggers PublishAndHandover, which fails on the empty scope and moves
        # the project into PUBLISH_PENDING_REPAIR with a genuine gate decision.
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(leader),
            stage_gate_public_id=gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="Seed repair-retry management conclusion.",
            idempotency_key=f"e2e-repair-retry-mgmt-{project.public_id}",
        ).execute()
        final = RecordFirstLaunchFinalDecision(
            context=CommandContext.for_actor(approver),
            stage_gate_public_id=gate.public_id,
            final_decision=GateResult.APPROVED,
            decision_summary="Seed repair-retry final decision.",
            idempotency_key=f"e2e-repair-retry-final-{project.public_id}",
        ).execute()

        project.refresh_from_db()
        if project.status != ProjectStatus.PUBLISH_PENDING_REPAIR:
            raise CommandError(
                "Repair-retry project did not enter PUBLISH_PENDING_REPAIR "
                f"(status={project.status}, handover_error={final.handover_error})."
            )

        # Repair the underlying data (populate the scope) so a subsequent retry
        # with the original decision publishes successfully.
        repaired_draft = project.product_draft
        if repaired_draft is None:
            raise CommandError("Repair-retry project is missing its product draft.")
        repaired_draft.change_scope = {
            "effective_from": timezone.now().isoformat(),
            "skus": [
                {
                    "sku_code": f"SKU-{business_no}",
                    "name": "Repaired cup",
                    "barcode": f"69{abs(hash(business_no)) % 10_000_000_000:010d}",
                    "specification": "120g",
                }
            ],
            "channels": [
                {
                    "sku_code": f"SKU-{business_no}",
                    "channel_code": "TMALL",
                    "channel_status": "ON_SALE",
                }
            ],
        }
        repaired_draft.save(update_fields=["change_scope", "updated_at"])

    def _rearm_repair_retry_project(self, project: Project, *, business_no: str) -> None:
        """Re-drive a real publish failure so every E2E run starts from PENDING_REPAIR.

        Clears prior publish artifacts, resets the FIRST_LAUNCH decision, empties the
        draft scope, re-submits the gate, and re-records dual-actor decisions so
        PublishAndHandover fails again with audit/outbox. Then repairs the scope so
        the UI retry can succeed.
        """

        from apps.operations.models import MonitoringScope
        from apps.platform.application.command import CommandContext
        from apps.products.models import (
            SKU,
            ChangeSetStatus,
            ChannelConfiguration,
            ProductAsset,
            ProductLifecycleStatus,
            ProductVersion,
            ProductVersionScope,
        )
        from apps.projects.models import ProjectStatus
        from apps.stage_gates.models import GateResult, MajorGateDecision, StageGateInstance
        from apps.stage_gates.services.record_first_launch_decision import (
            RecordFirstLaunchFinalDecision,
            RecordFirstLaunchManagementConclusion,
        )

        leader = project.leader
        if leader is None:
            raise CommandError("Repair-retry project is missing its leader.")
        approver = User.objects.filter(login_key=E2E_APPROVER_LOGIN_KEY).first()
        if approver is None:
            raise CommandError("Approver must be seeded before the repair-retry project.")

        MonitoringScope.objects.filter(project=project).delete()
        draft = project.product_draft
        if draft is None:
            raise CommandError("Repair-retry project is missing its product draft.")

        versions = list(ProductVersion.objects.filter(change_set=draft))
        version_ids = [version.id for version in versions]
        if version_ids:
            ChannelConfiguration.objects.filter(sku__product_version_id__in=version_ids).delete()
            SKU.objects.filter(product_version_id__in=version_ids).delete()
            ProductVersionScope.objects.filter(product_version_id__in=version_ids).delete()
            ProductAsset.objects.filter(primary_version_id__in=version_ids).update(
                primary_version=None
            )
            ProductVersion.objects.filter(id__in=version_ids).delete()

        # Empty scope so the re-driven publish fails for real.
        draft.change_scope = {
            "effective_from": timezone.now().isoformat(),
            "skus": [],
            "channels": [],
        }
        draft.status = ChangeSetStatus.APPROVED
        draft.save(update_fields=["change_scope", "status", "updated_at"])

        product = project.product_asset
        if product is not None:
            product.lifecycle_status = ProductLifecycleStatus.DEVELOPING
            product.save(update_fields=["lifecycle_status", "updated_at"])

        MajorGateDecision.objects.filter(
            stage_gate__project=project,
            stage_gate__stage_code="FIRST_LAUNCH",
        ).delete()
        StageGateInstance.objects.filter(project=project, stage_code="FIRST_LAUNCH").update(
            current_submission=None
        )

        project.status = ProjectStatus.ACTIVE
        project.save(update_fields=["status", "updated_at"])

        gate = self._submit_first_launch_gate(project, submitter=leader)
        RecordFirstLaunchManagementConclusion(
            context=CommandContext.for_actor(leader),
            stage_gate_public_id=gate.public_id,
            management_conclusion=GateResult.APPROVED,
            decision_summary="Re-arm repair-retry management conclusion.",
            idempotency_key=f"e2e-repair-retry-mgmt-{project.public_id}-{timezone.now().timestamp()}",
        ).execute()
        final = RecordFirstLaunchFinalDecision(
            context=CommandContext.for_actor(approver),
            stage_gate_public_id=gate.public_id,
            final_decision=GateResult.APPROVED,
            decision_summary="Re-arm repair-retry final decision.",
            idempotency_key=f"e2e-repair-retry-final-{project.public_id}-{timezone.now().timestamp()}",
        ).execute()

        project.refresh_from_db()
        if project.status != ProjectStatus.PUBLISH_PENDING_REPAIR:
            raise CommandError(
                "Repair-retry re-arm did not enter PUBLISH_PENDING_REPAIR "
                f"(status={project.status}, handover_error={final.handover_error})."
            )

        draft.change_scope = {
            "effective_from": timezone.now().isoformat(),
            "skus": [
                {
                    "sku_code": f"SKU-{business_no}",
                    "name": "Repaired cup",
                    "barcode": f"69{abs(hash(business_no)) % 10_000_000_000:010d}",
                    "specification": "120g",
                }
            ],
            "channels": [
                {
                    "sku_code": f"SKU-{business_no}",
                    "channel_code": "TMALL",
                    "channel_status": "ON_SALE",
                }
            ],
        }
        draft.save(update_fields=["change_scope", "updated_at"])

    def _submit_first_launch_gate(self, project: Project, *, submitter: User) -> StageGateInstance:
        """Put the FIRST_LAUNCH gate into a decideable SUBMITTED + active L2 state."""

        from apps.projects.models import ProjectStageStatus
        from apps.stage_gates.models import (
            GateStatus,
            GateSubmission,
            GateType,
            MaterialType,
            StageGateInstance,
            SubjectType,
        )

        stage = project.stages.get(stage_code="L2")
        stage.status = ProjectStageStatus.ACTIVE
        stage.actual_start_at = stage.actual_start_at or timezone.now()
        stage.save(update_fields=["status", "actual_start_at", "updated_at"])
        project.current_stage = stage
        project.save(update_fields=["current_stage", "updated_at"])

        gate = StageGateInstance.objects.filter(
            project=project,
            stage_code="FIRST_LAUNCH",
            cycle_number=1,
        ).first()
        if gate is None:
            raise CommandError("FIRST_LAUNCH gate missing for repair-retry project.")
        gate.gate_type = GateType.MAJOR
        gate.project_stage = stage
        gate.status = GateStatus.READY
        gate.primary_material_type = MaterialType.PROJECT_STAGE
        gate.primary_material_public_id = stage.public_id
        gate.subject_type = SubjectType.PROJECT
        gate.subject_public_id = project.public_id
        gate.save(
            update_fields=[
                "gate_type",
                "project_stage",
                "status",
                "primary_material_type",
                "primary_material_public_id",
                "subject_type",
                "subject_public_id",
                "updated_at",
            ]
        )

        submission = gate.current_submission
        if submission is None:
            submission = GateSubmission.objects.create(
                organization=project.organization,
                stage_gate=gate,
                submission_number=1,
                snapshot_json={"stage_code": "L2", "gate_code": "FIRST_LAUNCH"},
                content_hash=f"e2e-first-launch-{gate.public_id}",
                validation_result_json={"blocks": [], "warnings": []},
                submitted_by=submitter,
                submitted_at=timezone.now(),
                idempotency_key=f"e2e-repair-submit-{gate.public_id}",
            )
        gate.status = GateStatus.SUBMITTED
        gate.current_submission = submission
        gate.save(update_fields=["status", "current_submission", "updated_at"])
        return gate

    def _ensure_launch_project(
        self,
        organization: Organization,
        leader: User,
        *,
        business_no: str,
        name: str,
        publishable: bool,
    ) -> None:
        from apps.platform.application.command import CommandContext
        from apps.products.models import (
            ChangeSetStatus,
            ChangeSetType,
            ProductAsset,
            ProductChangeSet,
            ProductLifecycleStatus,
            ProductSourceType,
        )
        from apps.projects.models import Project, ProjectStatus, ProjectType
        from apps.projects.services.initialize_runtime import InitializeProjectRuntime
        from apps.stage_gates.models import GateStatus, StageGateInstance

        project = Project.objects.filter(organization=organization, business_no=business_no).first()
        if project is not None and project.status in {
            ProjectStatus.OPERATING,
            ProjectStatus.PUBLISH_PENDING_REPAIR,
        }:
            return

        if project is None:
            product = ProductAsset.objects.create(
                organization=organization,
                business_no=f"{business_no}-PRD",
                name=name,
                brand_code="BRAND-A",
                category_code="YOGURT",
                source_type=ProductSourceType.NEW_PROJECT,
                lifecycle_status=ProductLifecycleStatus.DEVELOPING,
                product_owner=leader,
            )
            change_scope = (
                {
                    "effective_from": timezone.now().isoformat(),
                    "skus": [
                        {
                            "sku_code": f"SKU-{business_no}",
                            "name": "Launch cup",
                            "barcode": f"69{abs(hash(business_no)) % 10_000_000_000:010d}",
                            "specification": "120g",
                        }
                    ],
                    "channels": [
                        {
                            "sku_code": f"SKU-{business_no}",
                            "channel_code": "TMALL",
                            "channel_status": "ON_SALE",
                        }
                    ],
                }
                if publishable
                else {"effective_from": timezone.now().isoformat(), "skus": [], "channels": []}
            )
            draft = ProductChangeSet.objects.create(
                organization=organization,
                change_type=ChangeSetType.NEW_PRODUCT,
                status=ChangeSetStatus.APPROVED,
                product=product,
                target_product_asset=product,
                title=f"{name} draft",
                change_scope=change_scope,
                approved_by=leader,
                created_by=leader,
            )
            project = Project.objects.create(
                organization=organization,
                business_no=business_no,
                name=name,
                project_type=ProjectType.NEW_PRODUCT,
                status=ProjectStatus.INITIALIZING,
                leader=leader,
                product_asset=product,
                product_draft=draft,
                idempotency_key=f"e2e-seed-{business_no}",
            )
            product.source_project = project
            product.save(update_fields=["source_project", "updated_at"])
            InitializeProjectRuntime(
                context=CommandContext.for_actor(leader),
                project=project,
            ).execute()
            project.refresh_from_db()
        else:
            existing_draft = project.product_draft
            if existing_draft is None:
                raise CommandError(f"Seed project {business_no} is missing product_draft.")
            draft = existing_draft
            if publishable:
                draft.change_scope = {
                    "effective_from": timezone.now().isoformat(),
                    "skus": [
                        {
                            "sku_code": f"SKU-{business_no}",
                            "name": "Launch cup",
                            "barcode": f"69{abs(hash(business_no)) % 10_000_000_000:010d}",
                            "specification": "120g",
                        }
                    ],
                    "channels": [
                        {
                            "sku_code": f"SKU-{business_no}",
                            "channel_code": "TMALL",
                            "channel_status": "ON_SALE",
                        }
                    ],
                }
            else:
                draft.change_scope = {
                    "effective_from": timezone.now().isoformat(),
                    "skus": [],
                    "channels": [],
                }
            draft.status = ChangeSetStatus.APPROVED
            draft.approved_by = leader
            draft.save(update_fields=["change_scope", "status", "approved_by", "updated_at"])
            if project.template_snapshot_id is None:
                InitializeProjectRuntime(
                    context=CommandContext.for_actor(leader),
                    project=project,
                ).execute()
                project.refresh_from_db()

        # Runtime init already expands tasks/deliverables/gates from the published template.
        # Only advance FIRST_LAUNCH to SUBMITTED for launch/repair decision fixture paths.

        stage = project.stages.get(stage_code="L2")
        gate = (
            StageGateInstance.objects.filter(
                project=project,
                stage_code="FIRST_LAUNCH",
                cycle_number=1,
            )
            .select_related("project_stage")
            .first()
        )
        if gate is None:
            raise RuntimeError("FIRST_LAUNCH gate missing after InitializeProjectRuntime")
        if gate.status not in {GateStatus.DECIDED, GateStatus.APPROVED}:
            gate.status = GateStatus.SUBMITTED
            gate.project_stage = stage
            gate.save(update_fields=["status", "project_stage", "updated_at"])
