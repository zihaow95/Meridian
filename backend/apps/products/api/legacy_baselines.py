"""Item-by-item legacy baseline entry."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext
from apps.products.api.schemas import (
    LEGACY_BASELINE_CREATE_REQUEST_SCHEMA,
    LEGACY_BASELINE_DRAFT_SCHEMA,
)
from apps.products.models import ProductAsset
from apps.products.services.create_legacy_baseline import (
    CreateLegacyBaselineDraft,
    find_draft_by_idempotency_key,
)
from apps.products.services.duplicate_detection import (
    detect_duplicate_candidates,
    serialize_candidates,
)

LegacyBaselineDraftPermission = requires_action(
    action_code="legacy_baseline.draft.create",
    resource_type="product_change_set",
)

CREATE = "CREATE"
LINK = "LINK"


class LegacyBaselineDraftCreateView(APIView):
    permission_classes = [IsAuthenticated, LegacyBaselineDraftPermission]

    @extend_schema(
        operation_id="legacy_baselines_create",
        request=LEGACY_BASELINE_CREATE_REQUEST_SCHEMA,
        responses={200: LEGACY_BASELINE_DRAFT_SCHEMA, 201: LEGACY_BASELINE_DRAFT_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        body = request.data
        payload: dict[str, Any] = dict(body.get("payload") or {})
        idempotency_key = str(body.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValidationFailedError(message="idempotency_key is required.")

        # A replay is not a new decision about duplicates: the user already made
        # one, so answer with what was created then.
        replay = find_draft_by_idempotency_key(
            organization_id=user.organization_id, idempotency_key=idempotency_key
        )
        if replay is not None:
            return Response(
                {
                    "change_set_public_id": str(replay.public_id),
                    "product_public_id": str(replay.product.public_id),
                    "created": False,
                    "duplicate_candidates": [],
                }
            )

        decision = str(body.get("decision") or "").upper()
        candidates = detect_duplicate_candidates(
            organization_id=user.organization_id, payload=payload
        )
        serialized = serialize_candidates(candidates)
        if any(candidate.blocking for candidate in candidates) and decision not in {CREATE, LINK}:
            # The user decides: create anyway, link to the existing product, or
            # walk away. Nothing is merged for them.
            raise ValidationFailedError(
                message="This product looks like one that already exists.",
                details={
                    "reason": "DUPLICATE_REQUIRES_DECISION",
                    "duplicate_candidates": serialized,
                },
            )

        existing_product = None
        business_no = str(payload.get("business_no") or "").strip()
        if decision != LINK and business_no:
            taken = ProductAsset.objects.filter(
                organization_id=user.organization_id, business_no=business_no
            ).exists()
            if taken:
                raise ValidationFailedError(
                    message="That business number already belongs to another product.",
                    details={
                        "reason": "BUSINESS_NO_TAKEN",
                        "duplicate_candidates": serialized,
                    },
                )

        if decision == LINK:
            target_raw = body.get("target_product_public_id")
            if not target_raw:
                raise ValidationFailedError(
                    message="target_product_public_id is required to link an existing product."
                )
            existing_product = ProductAsset.objects.filter(
                public_id=UUID(str(target_raw)), organization_id=user.organization_id
            ).first()
            if existing_product is None:
                raise ResourceNotFoundError()

        draft = CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(user),
            payload=payload,
            idempotency_key=idempotency_key,
            existing_product=existing_product,
        ).execute()

        return Response(
            {
                "change_set_public_id": str(draft.change_set.public_id),
                "product_public_id": str(draft.product.public_id),
                "created": draft.created,
                "duplicate_candidates": serialized,
            },
            status=201 if draft.created else 200,
        )
