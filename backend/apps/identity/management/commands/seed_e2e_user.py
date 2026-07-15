"""Seed deterministic fixtures for E2E and local smoke runs."""

from __future__ import annotations

from uuid import uuid4

from django.core.management.base import BaseCommand
from django.utils import timezone

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

_PHASE4_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("project_migration.confirm", "project", "PRODUCT_DIRECTOR"),
    ("first_launch.management_conclusion.record", "stage_gate", "BOSS"),
    ("first_launch.final_decision.record", "stage_gate", "BOSS"),
    ("emergency_execution.create", "project", "PRODUCT_DIRECTOR"),
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
        ConfigurationVersion.objects.update_or_create(
            organization=organization,
            definition=definition,
            version_number=1,
            defaults={
                "status": ConfigurationStatus.PUBLISHED,
                "content_json": {
                    "member_limit": 8,
                    "eligible_proposer_roles": ["PROPOSER"],
                    "management_conclusion_roles": ["MANAGEMENT_COMMITTEE", "BOSS"],
                    "final_decision_roles": ["BOSS"],
                    "product_manager_roles": ["PRODUCT_MANAGER"],
                    "case_leadership_roles": ["PRODUCT_DIRECTOR"],
                    "quota_enforcement_mode": "WARN",
                    "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
                },
                "created_by": actor,
                "published_by": actor,
                "published_at": timezone.now(),
            },
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
        import json
        from pathlib import Path

        seed_path = (
            Path(__file__).resolve().parents[3]
            / "configuration"
            / "defaults"
            / "project_template_v1.json"
        )
        content = json.loads(seed_path.read_text(encoding="utf-8"))
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code="PROJECT_EXECUTION_TEMPLATE",
            defaults={"name": "Project execution template"},
        )
        ConfigurationVersion.objects.update_or_create(
            organization=organization,
            definition=definition,
            version_number=1,
            defaults={
                "status": ConfigurationStatus.PUBLISHED,
                "content_json": content,
                "content_digest": "digest-e2e-project-template-v1",
                "created_by": actor,
                "published_by": actor,
                "published_at": timezone.now(),
            },
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
            draft = project.product_draft
            assert draft is not None
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
