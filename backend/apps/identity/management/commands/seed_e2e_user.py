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
E2E_ORG_NAME = "E2E Organization"

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
    ("migration.upload", "migration", "PRODUCT_DIRECTOR"),
    ("migration.review", "migration", "PRODUCT_DIRECTOR"),
    ("migration.confirm", "migration", "PRODUCT_DIRECTOR"),
    ("product.publish_baseline", "product", "PRODUCT_DIRECTOR"),
    ("external_binding.manage", "product", "PRODUCT_DIRECTOR"),
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
        self._publish_opportunity_rules(organization, user)

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
