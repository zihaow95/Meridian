"""Seed deterministic fixtures for E2E and local smoke runs."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

if TYPE_CHECKING:
    from apps.projects.models import Project
    from apps.stage_gates.models import StageGateInstance

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
    ("document.version.download", "document.version", "PRODUCT_DIRECTOR"),
    ("first_launch.management_conclusion.record", "stage_gate", "MANAGEMENT_COMMITTEE"),
    ("emergency_execution.create", "project", "PRODUCT_DIRECTOR"),
    ("emergency_execution.complete", "project", "PRODUCT_DIRECTOR"),
    ("project.publish_repair", "project", "PRODUCT_DIRECTOR"),
    ("plan_change.apply_minor", "project", "PRODUCT_DIRECTOR"),
    ("plan_change.confirm_important", "project", "PRODUCT_DIRECTOR"),
    ("task.create", "project", "PRODUCT_DIRECTOR"),
    ("deliverable.create", "project", "PRODUCT_DIRECTOR"),
)

# Active user = operating supervisor + config actor + retirement management conclusion.
# Final retirement decision stays on the approver (dual-control).
_PHASE5_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("operating_fact.read", "operating_fact", "OPERATING_SUPERVISOR"),
    ("data_source.configure", "data_source", "OPERATING_SUPERVISOR"),
    ("configuration.version.publish", "configuration.version", "OPERATING_SUPERVISOR"),
    ("ingestion_batch.create", "ingestion_batch", "OPERATING_SUPERVISOR"),
    ("ingestion_batch.confirm", "ingestion_batch", "OPERATING_SUPERVISOR"),
    ("ingestion_batch.retry", "ingestion_batch", "OPERATING_SUPERVISOR"),
    ("mapping.resolve", "ingestion_batch", "OPERATING_SUPERVISOR"),
    ("monitoring_scope.manage", "monitoring_scope", "OPERATING_SUPERVISOR"),
    ("manual_effective_value.create", "operating_value", "OPERATING_SUPERVISOR"),
    ("manual_effective_value.modify", "operating_value", "OPERATING_SUPERVISOR"),
    ("manual_effective_value.revoke", "operating_value", "OPERATING_SUPERVISOR"),
    ("metric_rule.configure", "metric_definition", "OPERATING_SUPERVISOR"),
    ("risk_signal.read", "risk_signal", "OPERATING_SUPERVISOR"),
    ("risk_signal.close", "risk_signal", "OPERATING_SUPERVISOR"),
    ("risk_signal.escalate", "risk_signal", "OPERATING_SUPERVISOR"),
    ("operating_issue.create", "operating_issue", "OPERATING_SUPERVISOR"),
    ("operating_issue.analyze", "operating_issue", "OPERATING_SUPERVISOR"),
    ("operating_issue.close", "operating_issue", "OPERATING_SUPERVISOR"),
    ("iteration_proposal.convert", "operating_issue", "OPERATING_SUPERVISOR"),
    ("retirement_plan.create", "retirement_plan", "OPERATING_SUPERVISOR"),
    ("retirement_plan.submit", "retirement_plan", "OPERATING_SUPERVISOR"),
    ("retirement_plan.execute", "retirement_plan", "OPERATING_SUPERVISOR"),
    ("retirement.management_conclusion.record", "stage_gate", "MANAGEMENT_COMMITTEE"),
    ("document.version.upload", "document.version", "OPERATING_SUPERVISOR"),
)

E2E_OPS_PRODUCT_BUSINESS_NO = "E2E-OPS-PRD"
E2E_OPS_SKU_CODE = "SKU-E2E-OPS"
E2E_OPS_CHANNEL_CODE = "TMALL"
E2E_OPS_SOURCE_CODE = "E2E_OPS_SRC"
E2E_OPS_METRIC_CODE = "PRODUCTION_QTY"
E2E_OPS_SALES_METRIC_CODE = "GROSS_SALES"
E2E_OPS_RULE_CODE = "E2E_QUARTER_SHELF_MIN_PROD"
E2E_OPS_MONITORING_DECISION_ID = UUID("1a09db77-b7f2-5c7a-8c59-fd509f67bbfb")


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
            was_active = user.status == UserStatus.ACTIVE
            user.organization = organization
            user.display_name = "E2E Active User"
            user.status = UserStatus.ACTIVE
            update_fields = ["organization", "display_name", "status"]
            if not was_active or user.activated_at is None:
                user.activated_at = timezone.now()
                update_fields.append("activated_at")
            user.save(update_fields=update_fields)

        self._grant_action(user, "notification.todo.read", "notification.todo")
        self._grant_action(user, "configuration.version.read", "configuration.version")
        self._grant_action(user, "configuration.draft.create", "configuration.version")
        self._grant_action(user, "configuration.version.publish", "configuration.version")
        for action_code, resource_type, role_code in _PHASE2_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        for action_code, resource_type, role_code in _PHASE3_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        for action_code, resource_type, role_code in _PHASE4_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        for action_code, resource_type, role_code in _PHASE5_ACTIONS:
            self._grant_action(user, action_code, resource_type, role_code=role_code)
        self._publish_opportunity_rules(organization, user)
        self._publish_product_schema(organization)
        self._publish_project_template(organization, user)
        self._ensure_approver(organization)
        self._ensure_limited_user(organization)
        self._ensure_phase4_projects(organization, user)
        self._ensure_phase5_operating_fixtures(organization, user)

        Todo.objects.update_or_create(
            assignee=user,
            dedup_key="e2e:todo",
            defaults={
                "organization": organization,
                "todo_type": "review",
                "source_type": "identity.user",
                "source_id": user.public_id,
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
            was_active = limited.status == UserStatus.ACTIVE
            limited.organization = organization
            limited.display_name = "E2E Limited User"
            limited.status = UserStatus.ACTIVE
            update_fields = ["organization", "display_name", "status"]
            if not was_active or limited.activated_at is None:
                limited.activated_at = timezone.now()
                update_fields.append("activated_at")
            limited.save(update_fields=update_fields)
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
            was_active = approver.status == UserStatus.ACTIVE
            approver.organization = organization
            approver.display_name = "E2E Approver"
            approver.status = UserStatus.ACTIVE
            update_fields = ["organization", "display_name", "status"]
            if not was_active or approver.activated_at is None:
                approver.activated_at = timezone.now()
                update_fields.append("activated_at")
            approver.save(update_fields=update_fields)
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
            # PRODUCT_RETIREMENT final decision — dual-control vs active user mgmt.
            ("retirement.final_decision.record", "stage_gate", "BOSS"),
            # Project creation pins the published template via CreateSnapshot.
            ("configuration.version.read", "configuration.version", "BOSS"),
            ("major_gate.final_decision.record", "stage_gate", "BOSS"),
            ("major_gate.management_conclusion.record", "stage_gate", "BOSS"),
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

    def _ensure_phase5_operating_fixtures(
        self, organization: Organization, supervisor: User
    ) -> None:
        """Seed OPERATING catalog + published source/metric/rule + monitoring assignment.

        Does not create RiskSignal / OperatingIssue decisions / Retirement final decisions.
        """

        from datetime import timedelta

        from apps.authorization.models.role import DataSensitivityLevel
        from apps.identity.models.department import Department, DepartmentStatus
        from apps.integrations.models import DataSource, DataSourceType
        from apps.integrations.services.data_sources import ConfigureOperatingDataSource
        from apps.operations.models import (
            CalculationType,
            MetricDefinitionStatus,
            MetricDefinitionVersion,
            MonitoringScopeType,
            RiskRuleStatus,
            RiskRuleVersion,
        )
        from apps.operations.services.initialize_monitoring_scope import (
            InitializeMonitoringScope,
        )
        from apps.operations.services.metric_definitions import (
            CreateMetricDefinitionDraft,
            PublishMetricDefinition,
        )
        from apps.operations.services.monitoring_assignments import AssignMonitoringSupervisor
        from apps.operations.services.risk_rules import (
            QUARTER_SHELF_LIFE_MIN_PRODUCTION,
            CreateRiskRuleDraft,
            PublishRiskRule,
        )
        from apps.platform.application.command import CommandContext
        from apps.products.models import (
            SKU,
            ChannelConfiguration,
            ChannelStatus,
            ProductAsset,
            ProductionStatus,
            ProductLifecycleStatus,
            ProductSourceType,
            ProductVersion,
            ProductVersionStatus,
            SKUStatus,
        )
        from apps.projects.models import Project, ProjectStatus, ProjectType

        now = timezone.now()
        ctx = CommandContext.for_actor(supervisor)

        department, _ = Department.objects.get_or_create(
            organization=organization,
            department_code="OPS",
            defaults={
                "name": "OPS Department",
                "status": DepartmentStatus.ACTIVE,
                "valid_from": now,
            },
        )

        product = ProductAsset.objects.filter(
            organization=organization, business_no=E2E_OPS_PRODUCT_BUSINESS_NO
        ).first()
        if product is None:
            product = ProductAsset.objects.create(
                organization=organization,
                business_no=E2E_OPS_PRODUCT_BUSINESS_NO,
                name="E2E Operating Yogurt",
                brand_code="BRAND-A",
                category_code="YOGURT",
                source_type=ProductSourceType.NEW_PROJECT,
                lifecycle_status=ProductLifecycleStatus.ACTIVE,
                product_owner=supervisor,
            )
        else:
            product.lifecycle_status = ProductLifecycleStatus.ACTIVE
            product.product_owner = supervisor
            product.save(update_fields=["lifecycle_status", "product_owner", "updated_at"])

        version = (
            ProductVersion.objects.filter(organization=organization, product=product)
            .order_by("-id")
            .first()
        )
        if version is None:
            version = ProductVersion.objects.create(
                organization=organization,
                product=product,
                version_code="V1",
                version_name="Operating baseline",
                status=ProductVersionStatus.EFFECTIVE,
                published_at=now,
                published_by=supervisor,
                effective_from=now - timedelta(days=120),
            )
        product.primary_version = version
        product.save(update_fields=["primary_version", "updated_at"])

        sku, _ = SKU.objects.get_or_create(
            organization=organization,
            product_version=version,
            sku_code=E2E_OPS_SKU_CODE,
            defaults={
                "name": "E2E Ops Cup",
                "specification": "120g",
                "status": SKUStatus.ACTIVE,
                "production_status": ProductionStatus.IN_PRODUCTION,
            },
        )
        if (
            sku.status != SKUStatus.ACTIVE
            or sku.production_status != ProductionStatus.IN_PRODUCTION
        ):
            sku.status = SKUStatus.ACTIVE
            sku.production_status = ProductionStatus.IN_PRODUCTION
            sku.save(update_fields=["status", "production_status", "updated_at"])

        channel, _ = ChannelConfiguration.objects.get_or_create(
            organization=organization,
            sku=sku,
            channel_code=E2E_OPS_CHANNEL_CODE,
            defaults={
                "configuration_version": 1,
                "channel_status": ChannelStatus.ON_SALE,
            },
        )
        if channel.channel_status != ChannelStatus.ON_SALE:
            channel.channel_status = ChannelStatus.ON_SALE
            channel.save(update_fields=["channel_status", "updated_at"])

        project = Project.objects.filter(
            organization=organization, business_no="E2E-OPS-MON"
        ).first()
        if project is None:
            project = Project.objects.create(
                organization=organization,
                business_no="E2E-OPS-MON",
                name="E2E Ops Monitoring",
                project_type=ProjectType.NEW_PRODUCT,
                status=ProjectStatus.OPERATING,
                leader=supervisor,
                product_asset=product,
                idempotency_key="e2e-seed-ops-monitoring",
            )
        existing_scope = (
            project.monitoring_scopes.filter(product_version=version).order_by("id").first()
        )
        scope = InitializeMonitoringScope(
            project=project,
            product_version=version,
            owner=supervisor,
            source_decision_public_id=(
                existing_scope.source_decision_public_id
                if existing_scope is not None
                else E2E_OPS_MONITORING_DECISION_ID
            ),
            effective_at=now,
        ).execute()
        AssignMonitoringSupervisor(
            context=ctx,
            monitoring_scope_public_id=scope.public_id,
            supervisor_public_id=supervisor.public_id,
            scope_type=MonitoringScopeType.SKU_CHANNEL,
            product_public_id=product.public_id,
            sku_public_id=sku.public_id,
            channel_public_id=channel.public_id,
            max_data_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
        ).execute()

        if not DataSource.objects.filter(
            organization=organization, source_code=E2E_OPS_SOURCE_CODE
        ).exists():
            ConfigureOperatingDataSource(
                context=ctx,
                source_code=E2E_OPS_SOURCE_CODE,
                name="E2E Ops Source",
                source_type=DataSourceType.API,
                owner_department_public_id=department.public_id,
                sensitivity_level="SENSITIVE_CONTROLLED",
                mapping_content={
                    "source_priority": 10,
                    "mapping_rules": [
                        {"external_field": "sku_code", "internal_field": "sku_code"},
                        {"external_field": "channel_code", "internal_field": "channel_code"},
                        {
                            "external_field": "production_qty",
                            "internal_field": "numeric_value",
                        },
                        {
                            "external_field": "sales_amount",
                            "internal_field": "numeric_value",
                        },
                        {"external_field": "metric_code", "internal_field": "metric_code"},
                        {"external_field": "period_start", "internal_field": "period_start"},
                        {"external_field": "period_end", "internal_field": "period_end"},
                        {
                            "external_field": "period_granularity",
                            "internal_field": "period_granularity",
                        },
                        {"external_field": "unit", "internal_field": "unit"},
                        {"external_field": "currency", "internal_field": "currency"},
                        {
                            "external_field": "external_record_key",
                            "internal_field": "external_record_key",
                        },
                        {
                            "external_field": "source_timestamp",
                            "internal_field": "source_timestamp",
                        },
                    ],
                    "reasonable_ranges": {
                        "production_qty": {"min": "0", "max": "10000000"},
                        "sales_amount": {"min": "0", "max": "10000000"},
                    },
                },
            ).execute()

        def _ensure_metric(
            *,
            metric_code: str,
            name: str,
            source_field: str,
            unit: str,
            currency: str,
            granularity: str,
        ) -> MetricDefinitionVersion:
            existing = (
                MetricDefinitionVersion.objects.filter(
                    organization=organization,
                    metric_code=metric_code,
                    status=MetricDefinitionStatus.PUBLISHED,
                )
                .order_by("-version_number")
                .first()
            )
            if existing is not None:
                return existing
            draft = CreateMetricDefinitionDraft(
                context=ctx,
                metric_code=metric_code,
                name=name,
                value_type="DECIMAL",
                unit=unit,
                currency=currency,
                source_field_codes=[source_field],
                calculation_type=CalculationType.SUM,
                aggregation_rule={"by": ["SKU", "CHANNEL", "PRODUCT"]},
                window_definition={"granularity": granularity},
                coverage_requirement={"minimum_rate": "0.8"},
                valid_from=now - timedelta(days=400),
            ).execute()
            return PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()

        production_metric = _ensure_metric(
            metric_code=E2E_OPS_METRIC_CODE,
            name="E2E Production qty",
            source_field="production_qty",
            unit="EA",
            currency="NA",
            granularity="QUARTER",
        )
        _ensure_metric(
            metric_code=E2E_OPS_SALES_METRIC_CODE,
            name="E2E Gross sales",
            source_field="sales_amount",
            unit="CNY",
            currency="CNY",
            granularity="MONTH",
        )

        if not RiskRuleVersion.objects.filter(
            organization=organization,
            rule_code=E2E_OPS_RULE_CODE,
            status=RiskRuleStatus.PUBLISHED,
        ).exists():
            draft = CreateRiskRuleDraft(
                context=ctx,
                rule_code=E2E_OPS_RULE_CODE,
                name="E2E quarter shelf min production",
                metric_codes=[production_metric.metric_code],
                evaluator_code=QUARTER_SHELF_LIFE_MIN_PRODUCTION,
                parameters_json={
                    "min_production": "1000",
                    "shelf_life_days": "120",
                    "window_days": "90",
                    "target_digestion_ratio": "1.0",
                    "metric_code": production_metric.metric_code,
                    "applicable_sku_codes": [sku.sku_code],
                    "applicable_channel_codes": [channel.channel_code],
                },
                scope_type=MonitoringScopeType.SKU_CHANNEL,
                valid_from=now - timedelta(days=400),
            ).execute()
            PublishRiskRule(context=ctx, rule_public_id=draft.public_id).execute()

        self.stdout.write(
            self.style.SUCCESS(
                f"E2E ops fixtures ready: product={product.business_no} "
                f"sku={sku.sku_code} source={E2E_OPS_SOURCE_CODE}"
            )
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
        repaired_product = project.product_asset
        if repaired_product is not None:
            self._ensure_approved_product_label(product=repaired_product, actor=leader)

    def _rearm_repair_retry_project(self, project: Project, *, business_no: str) -> None:
        """Re-drive a real publish failure so every E2E run starts from PENDING_REPAIR.

        Clears prior publish artifacts, resets the FIRST_LAUNCH decision, empties the
        draft scope, re-submits the gate, and re-records dual-actor decisions so
        PublishAndHandover fails again with audit/outbox. Then repairs the scope so
        the UI retry can succeed.
        """

        from apps.operations.models import MonitoringAssignment, MonitoringScope
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

        scopes = MonitoringScope.objects.filter(project=project)
        MonitoringAssignment.objects.filter(monitoring_scope__in=scopes).delete()
        scopes.delete()
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
        product = project.product_asset
        if product is not None:
            self._ensure_approved_product_label(product=product, actor=project.leader)

    def _ensure_approved_product_label(self, *, product: object, actor: User) -> None:
        """Satisfy YOGURT ACTIVE material requirements via real confirmation facts."""

        import hashlib

        from django.conf import settings

        from apps.documents.models import (
            Document,
            DocumentSource,
            DocumentVersion,
            FileObject,
            StorageBackend,
            StorageStatus,
            VersionStatus,
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
        from apps.products.services.material_confirmations import (
            DecideMaterialConfirmation,
            SubmitMaterialConfirmation,
        )

        assert isinstance(product, ProductAsset)
        material = (
            ProductMaterial.objects.select_related("document_version__file_object")
            .filter(
                organization_id=product.organization_id,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=product.id,
                material_type_code="PRODUCT_LABEL",
                current_slot=1,
            )
            .first()
        )
        if material is not None and self._has_valid_approved_confirmation(material):
            return

        self._grant_action(actor, "product_material.manage", "product_material")
        self._grant_action(actor, "product_material.confirm", "product_material")

        storage_root = settings.FILE_STORAGE_ROOT
        storage_root.mkdir(parents=True, exist_ok=True)
        code = f"E2E-LABEL-{product.business_no}"
        document, _ = Document.objects.get_or_create(
            organization_id=product.organization_id,
            document_code=code,
            defaults={
                "title": f"Label for {product.business_no}",
                "source": DocumentSource.PRODUCT,
            },
        )
        payload = f"e2e-label-{product.business_no}".encode()
        digest = hashlib.sha256(payload).hexdigest()
        object_key = f"e2e/labels/{code}.bin"
        file_object, created = FileObject.objects.get_or_create(
            organization_id=product.organization_id,
            object_key=object_key,
            defaults={
                "storage_backend": StorageBackend.NAS_NFS,
                "size_bytes": len(payload),
                "sha256": digest,
                "detected_mime_type": "application/pdf",
                "storage_status": StorageStatus.ACTIVE,
            },
        )
        if created:
            path = storage_root / object_key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        version, _ = DocumentVersion.objects.get_or_create(
            organization_id=product.organization_id,
            document=document,
            version_number=1,
            defaults={
                "file_object": file_object,
                "original_filename": f"{code}.pdf",
                "declared_mime_type": "application/pdf",
                "detected_mime_type": "application/pdf",
                "status": VersionStatus.CONTROLLED,
                "catalog_item_code": "PRODUCT_LABEL",
                "uploaded_by": actor,
                "uploaded_at": timezone.now(),
            },
        )
        if material is None:
            material = ProductMaterial.objects.create(
                organization_id=product.organization_id,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=product.id,
                material_type_code="PRODUCT_LABEL",
                version_no=1,
                document_version=version,
                material_status=MaterialStatus.DRAFT,
                current_slot=1,
                sensitivity_level=version.sensitivity_level,
            )
        else:
            # Repair forged APPROVED rows that lack a bound confirmation fact.
            material.document_version = version
            material.sensitivity_level = version.sensitivity_level
            if material.current_slot is None:
                material.current_slot = 1
            if not self._has_valid_approved_confirmation(material):
                material.material_status = MaterialStatus.DRAFT
            material.save(
                update_fields=[
                    "document_version",
                    "sensitivity_level",
                    "current_slot",
                    "material_status",
                    "updated_at",
                ]
            )
        if self._has_valid_approved_confirmation(material):
            return

        pending = MaterialConfirmation.objects.filter(
            material=material,
            decision=MaterialConfirmationDecision.PENDING,
            superseded_at__isnull=True,
        ).first()
        if pending is None:
            pending = SubmitMaterialConfirmation(
                context=CommandContext.for_actor(actor),
                material_public_id=material.public_id,
                confirmer_public_id=actor.public_id,
                comment="E2E repair seed confirmation",
            ).execute()
        DecideMaterialConfirmation(
            context=CommandContext.for_actor(actor),
            confirmation_public_id=pending.public_id,
            decision=MaterialConfirmationDecision.APPROVED,
            comment="E2E repair seed approval",
        ).execute()

    def _has_valid_approved_confirmation(self, material: object) -> bool:
        from apps.products.models import (
            MaterialConfirmation,
            MaterialConfirmationDecision,
            MaterialStatus,
            ProductMaterial,
        )

        assert isinstance(material, ProductMaterial)
        if material.material_status != MaterialStatus.APPROVED:
            return False
        file_object = material.document_version.file_object
        return MaterialConfirmation.objects.filter(
            material=material,
            decision=MaterialConfirmationDecision.APPROVED,
            live_slot=1,
            document_version_id=material.document_version_id,
            content_hash=file_object.sha256,
            confirmer__isnull=False,
            superseded_at__isnull=True,
        ).exists()

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
            next_number = (
                GateSubmission.objects.filter(stage_gate=gate)
                .order_by("-submission_number")
                .values_list("submission_number", flat=True)
                .first()
                or 0
            ) + 1
            stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
            submission = GateSubmission.objects.create(
                organization=project.organization,
                stage_gate=gate,
                submission_number=next_number,
                snapshot_json={"stage_code": "L2", "gate_code": "FIRST_LAUNCH"},
                content_hash=f"e2e-first-launch-{gate.public_id}-{next_number}",
                validation_result_json={"blocks": [], "warnings": []},
                submitted_by=submitter,
                submitted_at=timezone.now(),
                idempotency_key=f"e2e-repair-submit-{gate.public_id}-{stamp}",
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
        # Launch/repair fixtures need a real SUBMITTED gate with current_submission so
        # management-conclusion / final-decision APIs are decideable (not bare status flip).
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
            self._submit_first_launch_gate(project, submitter=leader)
