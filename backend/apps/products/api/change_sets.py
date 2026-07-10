"""Product change set command and query APIs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError
from apps.platform.application.command import CommandContext
from apps.products.api.schemas import (
    CHANGE_SET_DETAIL_SCHEMA,
    EDIT_CHANGE_SET_REQUEST_SCHEMA,
    PUBLICATION_VALIDATION_SCHEMA,
    PUBLISH_CHANGE_SET_REQUEST_SCHEMA,
    PUBLISH_CHANGE_SET_RESPONSE_SCHEMA,
)
from apps.products.models import ProductChangeSet
from apps.products.queries.change_sets import serialize_change_set_detail, serialize_change_set_diff
from apps.products.services.confirm_attribute_group import (
    ApproveAttributeGroup,
    ReturnAttributeGroup,
)
from apps.products.services.edit_change_set import EditProductChangeSet
from apps.products.services.publish_change_set import PublishProductChangeSet
from apps.products.services.update_change_set_scope import UpdateProductChangeSetScope
from apps.products.services.validate_publication import ValidateProductPublication
from apps.products.services.workflow_change_set import (
    ApproveProductChangeSet,
    SubmitProductChangeSetConfirmation,
)

UPDATE_SCOPE_REQUEST_SCHEMA = inline_serializer(
    name="UpdateChangeSetScopeRequest",
    fields={
        "version_no": serializers.IntegerField(),
        "skus": serializers.ListField(required=False),
        "channels": serializers.ListField(required=False),
        "scopes": serializers.ListField(required=False),
    },
)

ATTRIBUTE_CONFIRMATION_REQUEST_SCHEMA = inline_serializer(
    name="AttributeConfirmationRequest",
    fields={
        "group_value_public_id": serializers.UUIDField(),
        "content_hash": serializers.CharField(),
        "comment": serializers.CharField(required=False),
    },
)


class ProductChangeSetDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="product_change_sets_retrieve", responses=CHANGE_SET_DETAIL_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change_set = (
            ProductChangeSet.objects.select_related("product")
            .filter(public_id=public_id, organization_id=user.organization_id)
            .first()
        )
        if change_set is None:
            raise ResourceNotFoundError()
        return Response(serialize_change_set_detail(change_set))


class ProductChangeSetDiffView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_diff_retrieve",
        responses=inline_serializer(
            name="ProductChangeSetDiffResponse",
            fields={"groups": serializers.ListField()},
        ),
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change_set = ProductChangeSet.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        ).first()
        if change_set is None:
            raise ResourceNotFoundError()
        return Response(serialize_change_set_diff(actor=user, change_set=change_set))


class ProductChangeSetEditView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_edit_group",
        request=EDIT_CHANGE_SET_REQUEST_SCHEMA,
        responses=CHANGE_SET_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        body = cast(dict[str, Any], request.data)
        EditProductChangeSet(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
            version_no=int(body["version_no"]),
            group_code=str(body["group_code"]),
            values=dict(body["values"]),
        ).execute()
        change_set = ProductChangeSet.objects.select_related("product").get(public_id=public_id)
        return Response(serialize_change_set_detail(change_set))


class ValidatePublicationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_validate_publication",
        responses=PUBLICATION_VALIDATION_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        result = ValidateProductPublication(
            actor=user,
            change_set_public_id=public_id,
        ).execute()
        return Response(
            {
                "can_publish": result.can_publish,
                "blocks": [
                    {"code": block.code, "message": block.message} for block in result.blocks
                ],
            }
        )


class PublishChangeSetView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_publish",
        request=PUBLISH_CHANGE_SET_REQUEST_SCHEMA,
        responses=PUBLISH_CHANGE_SET_RESPONSE_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        body = cast(dict[str, Any], request.data)
        result = PublishProductChangeSet(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
            idempotency_key=str(body["idempotency_key"]),
        ).execute()
        return Response(
            {
                "change_set_public_id": str(result.change_set.public_id),
                "product_version_public_id": str(result.product_version.public_id),
                "product_lifecycle_status": result.change_set.product.lifecycle_status,
            }
        )


class SubmitChangeSetConfirmationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_submit_confirmation",
        responses=CHANGE_SET_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change_set = SubmitProductChangeSetConfirmation(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
        ).execute()
        return Response(serialize_change_set_detail(change_set))


class ApproveChangeSetView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_approve",
        responses=CHANGE_SET_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        change_set = ApproveProductChangeSet(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
        ).execute()
        return Response(serialize_change_set_detail(change_set))


class UpdateChangeSetScopeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_update_scope",
        request=UPDATE_SCOPE_REQUEST_SCHEMA,
        responses=CHANGE_SET_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        body = cast(dict[str, Any], request.data)
        change_set = UpdateProductChangeSetScope(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
            version_no=int(body["version_no"]),
            skus=body.get("skus"),
            channels=body.get("channels"),
            scopes=body.get("scopes"),
        ).execute()
        return Response(serialize_change_set_detail(change_set))


class ApproveAttributeGroupView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_approve_attribute_group",
        request=ATTRIBUTE_CONFIRMATION_REQUEST_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        body = cast(dict[str, Any], request.data)
        ApproveAttributeGroup(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
            group_value_public_id=UUID(str(body["group_value_public_id"])),
            content_hash=str(body["content_hash"]),
            comment=str(body.get("comment") or ""),
        ).execute()
        change_set = ProductChangeSet.objects.select_related("product").get(public_id=public_id)
        return Response(serialize_change_set_detail(change_set))


class ReturnAttributeGroupView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="product_change_sets_return_attribute_group",
        request=ATTRIBUTE_CONFIRMATION_REQUEST_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        body = cast(dict[str, Any], request.data)
        ReturnAttributeGroup(
            context=CommandContext.for_actor(user),
            change_set_public_id=public_id,
            group_value_public_id=UUID(str(body["group_value_public_id"])),
            content_hash=str(body["content_hash"]),
            comment=str(body.get("comment") or ""),
        ).execute()
        change_set = ProductChangeSet.objects.select_related("product").get(public_id=public_id)
        return Response(serialize_change_set_detail(change_set))
