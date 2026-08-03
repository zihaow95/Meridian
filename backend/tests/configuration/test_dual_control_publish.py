"""Publishing a critical configuration takes two people, not one boolean.

Before phase 6 the only evidence of business sign-off was a `business_confirmed`
default of True that no caller ever set, so a single administrator could publish
the rules that govern controlled files and notifications. Phase 6 routes those
definitions through the existing AdminChangeRequest state machine, using
configuration-specific actions so that reviewing a publication does not grant
generic administrative review authority.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.authorization.models.admin_change import AdminChangeStatus
from apps.authorization.services.request_admin_change import get_security_setting
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import (
    FILE_UPLOAD_DEFINITION_CODE,
    TECHNICAL_FILE_CATALOG_CODE,
)
from apps.configuration.services import (
    CreateDraft,
    PublicationApprovalInvalid,
    PublicationApprovalRequired,
    PublishVersion,
    RequestConfigurationPublication,
    ReviewConfigurationPublication,
)
from apps.platform.application.command import CommandContext

REQUEST_ACTION = "configuration.publication.request"
REVIEW_ACTION = "configuration.publication.review"
RESOURCE_TYPE = "configuration.version"


def catalog_content() -> dict[str, Any]:
    return {
        "catalog_items": [
            {
                "item_code": "PRODUCT_SPEC",
                "name": "Product specification",
                "allowed_mime_types": ["application/pdf"],
                "max_bytes": 52_428_800,
                "preview_enabled": True,
                "default_sensitivity_level": "SENSITIVE_CONTROLLED",
                "retention_years": 5,
            }
        ]
    }


@pytest.fixture
def catalog_draft(organization, active_user) -> ConfigurationVersion:
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=TECHNICAL_FILE_CATALOG_CODE,
        name="Technical file catalog",
    )
    return CreateDraft(
        actor=active_user,
        definition=definition,
        content=catalog_content(),
    ).execute()


@pytest.fixture
def requester(active_user, grant_action):
    grant_action(active_user, REQUEST_ACTION, RESOURCE_TYPE)
    grant_action(active_user, "configuration.version.publish", RESOURCE_TYPE)
    return active_user


@pytest.fixture
def reviewer(another_active_user, grant_action):
    grant_action(another_active_user, REVIEW_ACTION, RESOURCE_TYPE)
    return another_active_user


def approved_request_for(draft: ConfigurationVersion, requester, reviewer):
    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(requester),
        version_public_id=draft.public_id,
    ).execute()
    return ReviewConfigurationPublication(
        context=CommandContext.for_actor(reviewer),
        request_public_id=request.public_id,
        decision=AdminChangeStatus.APPROVED,
    ).execute()


@pytest.mark.django_db
def test_critical_definition_cannot_be_published_without_an_approved_request(
    catalog_draft, active_user
) -> None:
    with pytest.raises(PublicationApprovalRequired):
        PublishVersion(version=catalog_draft, actor=active_user).execute()

    catalog_draft.refresh_from_db()
    assert catalog_draft.status == ConfigurationStatus.DRAFT


@pytest.mark.django_db
def test_requester_cannot_review_their_own_publication_request(
    catalog_draft, requester, grant_action
) -> None:
    grant_action(requester, REVIEW_ACTION, RESOURCE_TYPE)
    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(requester),
        version_public_id=catalog_draft.public_id,
    ).execute()

    from apps.authorization.services.review_admin_change import ReviewerMustDiffer

    with pytest.raises(ReviewerMustDiffer):
        ReviewConfigurationPublication(
            context=CommandContext.for_actor(requester),
            request_public_id=request.public_id,
            decision=AdminChangeStatus.APPROVED,
        ).execute()

    request.refresh_from_db()
    assert request.status == AdminChangeStatus.PENDING


@pytest.mark.django_db
def test_approved_request_publishes_the_version_and_is_marked_applied(
    catalog_draft, requester, reviewer
) -> None:
    approved = approved_request_for(catalog_draft, requester, reviewer)

    published = PublishVersion(
        version=catalog_draft, actor=requester, approved_request=approved
    ).execute()

    approved.refresh_from_db()
    assert published.status == ConfigurationStatus.PUBLISHED
    assert published.current_published_slot == 1
    assert approved.status == AdminChangeStatus.APPLIED


@pytest.mark.django_db
def test_rejected_request_does_not_publish(catalog_draft, requester, reviewer) -> None:
    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(requester),
        version_public_id=catalog_draft.public_id,
    ).execute()
    rejected = ReviewConfigurationPublication(
        context=CommandContext.for_actor(reviewer),
        request_public_id=request.public_id,
        decision=AdminChangeStatus.REJECTED,
    ).execute()

    with pytest.raises(PublicationApprovalInvalid):
        PublishVersion(version=catalog_draft, actor=requester, approved_request=rejected).execute()

    catalog_draft.refresh_from_db()
    assert catalog_draft.status == ConfigurationStatus.DRAFT


@pytest.mark.django_db
def test_an_approval_cannot_be_replayed_for_a_second_publication(
    catalog_draft, requester, reviewer, organization, active_user
) -> None:
    approved = approved_request_for(catalog_draft, requester, reviewer)
    PublishVersion(version=catalog_draft, actor=requester, approved_request=approved).execute()

    successor = CreateDraft(
        actor=active_user,
        definition=catalog_draft.definition,
        content=catalog_content(),
    ).execute()

    with pytest.raises(PublicationApprovalInvalid):
        PublishVersion(version=successor, actor=requester, approved_request=approved).execute()


@pytest.mark.django_db
def test_an_approval_for_another_version_cannot_publish_this_one(
    catalog_draft, requester, reviewer, active_user
) -> None:
    approved = approved_request_for(catalog_draft, requester, reviewer)
    other_draft = CreateDraft(
        actor=active_user,
        definition=catalog_draft.definition,
        content=catalog_content(),
    ).execute()

    with pytest.raises(PublicationApprovalInvalid):
        PublishVersion(version=other_draft, actor=requester, approved_request=approved).execute()


@pytest.mark.django_db
def test_expired_request_cannot_be_approved(catalog_draft, requester, reviewer) -> None:
    from apps.authorization.services.review_admin_change import AdminChangeNotPending

    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(requester),
        version_public_id=catalog_draft.public_id,
    ).execute()
    request.expires_at = timezone.now() - timedelta(minutes=1)
    request.save(update_fields=["expires_at", "updated_at"])

    with pytest.raises(AdminChangeNotPending):
        ReviewConfigurationPublication(
            context=CommandContext.for_actor(reviewer),
            request_public_id=request.public_id,
            decision=AdminChangeStatus.APPROVED,
        ).execute()


@pytest.mark.django_db
def test_generic_admin_change_review_does_not_authorize_a_configuration_publication(
    catalog_draft, requester, another_active_user, grant_action
) -> None:
    from apps.configuration.services import ConfigurationPublicationDenied

    grant_action(
        another_active_user,
        "authorization.admin_change.review",
        "authorization.admin_change_request",
    )
    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(requester),
        version_public_id=catalog_draft.public_id,
    ).execute()

    with pytest.raises(ConfigurationPublicationDenied):
        ReviewConfigurationPublication(
            context=CommandContext.for_actor(another_active_user),
            request_public_id=request.public_id,
            decision=AdminChangeStatus.APPROVED,
        ).execute()

    request.refresh_from_db()
    assert request.status == AdminChangeStatus.PENDING


@pytest.mark.django_db
def test_definitions_outside_the_critical_set_still_publish_directly(
    file_upload_definition, active_user
) -> None:
    draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()

    published = PublishVersion(version=draft, actor=active_user).execute()

    assert published.status == ConfigurationStatus.PUBLISHED


@pytest.mark.django_db
def test_enabling_dual_control_extends_the_requirement_to_every_definition(
    file_upload_definition, active_user
) -> None:
    setting = get_security_setting()
    setting.dual_control_enabled = True
    setting.save(update_fields=["dual_control_enabled"])
    draft = CreateDraft(
        actor=active_user,
        definition=file_upload_definition,
        content={"allowed_mime_types": ["application/pdf"], "max_bytes": 1_048_576},
    ).execute()

    with pytest.raises(PublicationApprovalRequired):
        PublishVersion(version=draft, actor=active_user).execute()

    assert FILE_UPLOAD_DEFINITION_CODE == file_upload_definition.definition_code
