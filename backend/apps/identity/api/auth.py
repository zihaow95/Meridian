"""Authentication endpoints."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import logout as django_logout
from django.http import HttpResponseBase
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.identity.services.authenticate_dingtalk import (
    DingTalkAuthCallback,
    DingTalkAuthStart,
    establish_session,
)
from apps.integrations.dingtalk.contracts import DingTalkGateway
from apps.platform.api.errors import (
    AuthenticationFailedError,
    UserNotActiveError,
    ValidationFailedError,
)


def _get_dingtalk_gateway() -> DingTalkGateway:
    gateway = getattr(settings, "DINGTALK_GATEWAY", None)
    if gateway is None:
        raise RuntimeError("DINGTALK_GATEWAY is not configured.")
    return gateway


class DingTalkStartView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_dingtalk_start",
        summary="Start DingTalk OAuth flow",
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseBase:
        next_path = request.query_params.get("next", "/")
        state, _ = DingTalkAuthStart(redirect_path=next_path).execute()
        callback_url = request.build_absolute_uri("/api/v1/auth/dingtalk/callback")
        gateway = _get_dingtalk_gateway()
        authorize_url = gateway.build_authorize_url(state=state, redirect_uri=callback_url)
        return redirect(authorize_url)


class CsrfView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(operation_id="auth_csrf_retrieve", responses={204: None})
    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        return Response(status=status.HTTP_204_NO_CONTENT)


class DingTalkCallbackView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_dingtalk_callback",
        summary="DingTalk OAuth callback",
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseBase:
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        user, redirect_path = DingTalkAuthCallback(
            code=code,
            state=state,
            gateway=_get_dingtalk_gateway(),
        ).execute()
        establish_session(request, user)
        return redirect(redirect_path)


class LogoutView(APIView):
    @extend_schema(operation_id="auth_logout", request=None, responses={204: None})
    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        django_logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DevLoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="auth_dev_login",
        request=inline_serializer(
            name="DevLoginRequest",
            fields={
                "login_key": serializers.CharField(),
            },
        ),
        responses={
            200: inline_serializer(
                name="DevLoginResponse",
                fields={
                    "public_id": serializers.CharField(),
                    "display_name": serializers.CharField(),
                },
            ),
            404: None,
        },
    )
    @method_decorator(csrf_protect)
    def post(self, request: Request) -> Response:
        if not getattr(settings, "ENABLE_DEV_LOGIN", False):
            return Response(status=status.HTTP_404_NOT_FOUND)

        login_key = request.data.get("login_key")
        if not login_key:
            raise ValidationFailedError(details={"login_key": ["This field is required."]})

        try:
            user = User.objects.get(login_key=login_key)
        except User.DoesNotExist:
            raise AuthenticationFailedError(message="Invalid login credentials.") from None

        if not user.is_active:
            raise UserNotActiveError()

        establish_session(request, user)
        return Response({"public_id": str(user.public_id), "display_name": user.display_name})
