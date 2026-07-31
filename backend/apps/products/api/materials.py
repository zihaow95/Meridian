"""Material workbench APIs: triage queue, version chains, confirmation, completeness."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext
from apps.products.api.schemas import (
    LEGACY_MATERIAL_CREATE_REQUEST_SCHEMA,
    LEGACY_MATERIAL_PAGE_SCHEMA,
    LEGACY_MATERIAL_SCHEMA,
    LEGACY_MATERIAL_VERIFY_REQUEST_SCHEMA,
    MATERIAL_CHAIN_CREATE_REQUEST_SCHEMA,
    MATERIAL_CHAIN_SCHEMA,
    MATERIAL_COMPLETENESS_SCHEMA,
    MATERIAL_CONFIRMATION_DECIDE_REQUEST_SCHEMA,
    MATERIAL_CONFIRMATION_REQUEST_SCHEMA,
    MATERIAL_CONFIRMATION_SCHEMA,
    MATERIAL_GROUP_PAGE_SCHEMA,
)
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialSubmission,
    MaterialConfirmation,
    ProductAsset,
    ProductMaterial,
)
from apps.products.services.legacy_material_intake import (
    CreateLegacyMaterialSubmission,
    LegacyMaterialIntakeFailed,
)
from apps.products.services.material_chains import (
    CreateLegacyMaterialVersionChain,
    MaterialChainRejected,
    MaterialOwner,
    VerifyLegacyMaterialSubmission,
)
from apps.products.services.material_confirmations import (
    DecideMaterialConfirmation,
    MaterialConfirmationRejected,
    SubmitMaterialConfirmation,
)
from apps.products.services.material_requirements import (
    MaterialRequirementsUnavailable,
    evaluate_material_completeness,
)

LegacyMaterialReadPermission = requires_action(
    action_code="legacy_material.submission.read",
    resource_type="legacy_material_submission",
)
LegacyMaterialCreatePermission = requires_action(
    action_code="legacy_material.submission.create",
    resource_type="legacy_material_submission",
)
MaterialReadPermission = requires_action(
    action_code="product_material.completeness.read",
    resource_type="product_material",
)


def _product_or_404(user: User, public_id: UUID) -> ProductAsset:
    product = ProductAsset.objects.filter(
        public_id=public_id, organization_id=user.organization_id
    ).first()
    if product is None:
        raise ResourceNotFoundError()
    return product


def _serialize_submission(submission: LegacyMaterialSubmission) -> dict[str, Any]:
    return {
        "public_id": str(submission.public_id),
        "document_version_public_id": str(submission.document_version.public_id),
        "processing_status": submission.processing_status,
        "source_note": submission.source_note,
        "original_file_date": (
            submission.original_file_date.isoformat() if submission.original_file_date else None
        ),
        "claimed_version": submission.claimed_version,
        "claimed_effective_from": (
            submission.claimed_effective_from.isoformat()
            if submission.claimed_effective_from
            else None
        ),
        "sha256": submission.sha256,
        "submitted_by_public_id": str(submission.submitted_by.public_id),
        "verified_by_public_id": (
            str(submission.verified_by.public_id) if submission.verified_by is not None else None
        ),
        "verification_note": submission.verification_note,
    }


def _serialize_material(material: ProductMaterial) -> dict[str, Any]:
    live = next(
        (item for item in material.confirmations.all() if item.live_slot == 1),
        None,
    )
    return {
        "public_id": str(material.public_id),
        "material_type_code": material.material_type_code,
        "version_no": material.version_no,
        "material_status": material.material_status,
        "is_current": material.current_slot == 1,
        "document_version_public_id": str(material.document_version.public_id),
        "original_filename": material.document_version.original_filename,
        "confirmation": _serialize_confirmation(live) if live is not None else None,
    }


def _serialize_confirmation(confirmation: MaterialConfirmation) -> dict[str, Any]:
    return {
        "public_id": str(confirmation.public_id),
        "decision": confirmation.decision,
        "confirmer_public_id": (
            str(confirmation.confirmer.public_id) if confirmation.confirmer is not None else None
        ),
        "content_hash": confirmation.content_hash,
        "requested_at": confirmation.requested_at.isoformat(),
        "decided_at": confirmation.decided_at.isoformat() if confirmation.decided_at else None,
    }


class ProductLegacyMaterialListView(APIView):
    permission_classes = [IsAuthenticated, LegacyMaterialReadPermission]

    @extend_schema(
        operation_id="products_legacy_materials_list",
        parameters=[
            OpenApiParameter(name="processing_status", type=str, location=OpenApiParameter.QUERY)
        ],
        responses=LEGACY_MATERIAL_PAGE_SCHEMA,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = _product_or_404(user, public_id)
        submissions = LegacyMaterialSubmission.objects.select_related(
            "document_version", "submitted_by", "verified_by"
        ).filter(
            organization_id=user.organization_id,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=product.id,
        )
        status_filter = request.query_params.get("processing_status")
        if status_filter:
            submissions = submissions.filter(processing_status=status_filter)
        return Response(
            {"items": [_serialize_submission(item) for item in submissions.order_by("created_at")]}
        )


class ProductLegacyMaterialCreateView(APIView):
    permission_classes = [IsAuthenticated, LegacyMaterialCreatePermission]

    @extend_schema(
        operation_id="products_legacy_materials_create",
        request=LEGACY_MATERIAL_CREATE_REQUEST_SCHEMA,
        responses={201: LEGACY_MATERIAL_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = _product_or_404(user, public_id)
        body = request.data
        try:
            result = CreateLegacyMaterialSubmission(
                context=CommandContext.for_actor(user),
                document_version_public_id=UUID(str(body["document_version_public_id"])),
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=product.id,
                idempotency_key=str(body["idempotency_key"]),
                source_note=str(body.get("source_note", "")),
                original_file_date=_optional_date(body.get("original_file_date")),
                claimed_version=str(body.get("claimed_version", "")),
                claimed_effective_from=_optional_date(body.get("claimed_effective_from")),
            ).execute()
        except KeyError as exc:
            raise ValidationFailedError(message=f"{exc.args[0]} is required.") from exc
        except LegacyMaterialIntakeFailed as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        payload = _serialize_submission(result.submission)
        payload["duplicate_candidates"] = [
            {
                "public_id": str(candidate.public_id),
                "owner_type": candidate.owner_type,
                "owner_id": candidate.owner_id,
            }
            for candidate in result.duplicate_candidates
        ]
        return Response(payload, status=201)


class LegacyMaterialVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="legacy_materials_verify",
        request=LEGACY_MATERIAL_VERIFY_REQUEST_SCHEMA,
        responses={200: LEGACY_MATERIAL_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            submission = VerifyLegacyMaterialSubmission(
                context=CommandContext.for_actor(user),
                submission_public_id=public_id,
                decision=str(request.data.get("decision", "")),
                note=str(request.data.get("note", "")),
            ).execute()
        except MaterialChainRejected as exc:
            raise ValidationFailedError(message=str(exc)) from exc
        return Response(_serialize_submission(submission))


class ProductMaterialChainCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="products_material_chains_create",
        request=MATERIAL_CHAIN_CREATE_REQUEST_SCHEMA,
        responses={201: MATERIAL_CHAIN_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = _product_or_404(user, public_id)
        body = request.data
        try:
            materials = CreateLegacyMaterialVersionChain(
                context=CommandContext.for_actor(user),
                ordered_submission_ids=[
                    UUID(str(value)) for value in body.get("ordered_submission_ids", [])
                ],
                current_submission_id=UUID(str(body["current_submission_id"])),
                owner=MaterialOwner(owner_type=AttributeOwnerType.PRODUCT, owner_id=product.id),
                material_type_code=str(body["material_type_code"]),
            ).execute()
        except KeyError as exc:
            raise ValidationFailedError(message=f"{exc.args[0]} is required.") from exc
        except (MaterialChainRejected, ValueError) as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        for material in materials:
            material.refresh_from_db()
        return Response(
            {"items": [_serialize_material(material) for material in materials]}, status=201
        )


class ProductMaterialListView(APIView):
    permission_classes = [IsAuthenticated, MaterialReadPermission]

    @extend_schema(
        operation_id="products_materials_list",
        responses=MATERIAL_GROUP_PAGE_SCHEMA,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = _product_or_404(user, public_id)
        materials = (
            ProductMaterial.objects.select_related("document_version")
            .prefetch_related("confirmations")
            .filter(
                organization_id=user.organization_id,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=product.id,
            )
            .order_by("material_type_code", "version_no")
        )

        groups: dict[str, dict[str, Any]] = {}
        for material in materials:
            group = groups.setdefault(
                material.material_type_code,
                {
                    "material_type_code": material.material_type_code,
                    "current": None,
                    "history": [],
                },
            )
            payload = _serialize_material(material)
            if material.current_slot == 1:
                group["current"] = payload
            else:
                group["history"].append(payload)
        return Response({"items": list(groups.values())})


class ProductMaterialCompletenessView(APIView):
    permission_classes = [IsAuthenticated, MaterialReadPermission]

    @extend_schema(
        operation_id="products_material_completeness_retrieve",
        parameters=[
            OpenApiParameter(name="lifecycle_state", type=str, location=OpenApiParameter.QUERY)
        ],
        responses=MATERIAL_COMPLETENESS_SCHEMA,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        product = _product_or_404(user, public_id)
        try:
            result = evaluate_material_completeness(
                organization=product.organization,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=product.id,
                product_category_code=product.category_code,
                lifecycle_state=request.query_params.get(
                    "lifecycle_state", product.lifecycle_status
                ),
            )
        except MaterialRequirementsUnavailable as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        return Response(
            {
                "requirement_version_public_id": str(result.requirement_version_public_id),
                "requirement_version_number": result.requirement_version_number,
                "requirement_content_digest": result.requirement_content_digest,
                "is_complete": result.is_complete,
                "blocking_material_type_codes": list(result.blocking_material_type_codes),
                "items": [
                    {
                        "material_type_code": item.material_type_code,
                        "requirement": item.requirement,
                        "state": item.state,
                    }
                    for item in result.items
                ],
            }
        )


class ProductMaterialConfirmationCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_materials_confirmations_create",
        request=MATERIAL_CONFIRMATION_REQUEST_SCHEMA,
        responses={201: MATERIAL_CONFIRMATION_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            confirmation = SubmitMaterialConfirmation(
                context=CommandContext.for_actor(user),
                material_public_id=public_id,
                confirmer_public_id=UUID(str(request.data["confirmer_public_id"])),
                comment=str(request.data.get("comment", "")),
            ).execute()
        except KeyError as exc:
            raise ValidationFailedError(message=f"{exc.args[0]} is required.") from exc
        except (MaterialConfirmationRejected, ValueError) as exc:
            raise ValidationFailedError(message=str(exc)) from exc
        return Response(_serialize_confirmation(confirmation), status=201)


class MaterialConfirmationDecideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="material_confirmations_decide",
        request=MATERIAL_CONFIRMATION_DECIDE_REQUEST_SCHEMA,
        responses={200: MATERIAL_CONFIRMATION_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            confirmation = DecideMaterialConfirmation(
                context=CommandContext.for_actor(user),
                confirmation_public_id=public_id,
                decision=str(request.data.get("decision", "")),
                comment=str(request.data.get("comment", "")),
            ).execute()
        except MaterialConfirmationRejected as exc:
            raise ValidationFailedError(message=str(exc)) from exc
        return Response(_serialize_confirmation(confirmation))


def _optional_date(raw: Any) -> Any:
    from datetime import date

    if raw in (None, ""):
        return None
    return date.fromisoformat(str(raw))
