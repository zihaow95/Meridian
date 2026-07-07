"""Authentication and session rules."""

from __future__ import annotations

import hashlib

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from apps.identity.models.binding import AuthState
from apps.integrations.dingtalk.contracts import DingTalkIdentity
from apps.integrations.dingtalk.http_gateway import HttpDingTalkGateway


@pytest.mark.django_db
def test_dingtalk_success_cannot_log_in_disabled_internal_user(
    client: Client,
    disabled_user,
    dingtalk_binding,
    fake_dingtalk_gateway,
    valid_auth_state: AuthState,
) -> None:
    fake_dingtalk_gateway.register(
        "valid",
        DingTalkIdentity(tenant_id="corp-1", user_id="user-1"),
    )
    response = client.get("/api/v1/auth/dingtalk/callback?code=valid&state=valid")

    assert response.status_code == 403
    assert response.json()["code"] == "USER_NOT_ACTIVE"
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_dingtalk_success_establishes_session_for_active_user(
    client: Client,
    active_user_dingtalk_setup,
    valid_auth_state: AuthState,
) -> None:
    AuthState.objects.create(
        state_hash=hashlib.sha256(b"active-state").hexdigest(),
        redirect_path="/dashboard",
        expires_at=timezone.now() + timezone.timedelta(minutes=10),
    )
    response = client.get("/api/v1/auth/dingtalk/callback?code=valid-active&state=active-state")

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(active_user_dingtalk_setup.pk)


@pytest.mark.django_db
def test_dev_login_rejects_disabled_user(client: Client, disabled_user) -> None:
    response = client.post(
        "/api/v1/auth/dev/login",
        data={"login_key": disabled_user.login_key},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["code"] == "USER_NOT_ACTIVE"


@pytest.mark.django_db
def test_dev_login_establishes_session_for_active_user(client: Client, active_user) -> None:
    response = client.post(
        "/api/v1/auth/dev/login",
        data={"login_key": active_user.login_key},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(active_user.pk)


@pytest.mark.django_db
def test_me_requires_authentication(client: Client) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 403


@pytest.mark.django_db
def test_me_returns_current_user(client: Client, active_user) -> None:
    client.force_login(active_user)
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["public_id"] == str(active_user.public_id)
    assert response.json()["display_name"] == active_user.display_name


def test_http_dingtalk_gateway_uses_injected_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        return httpx.Response(200, json={"tenant_id": "corp-x", "user_id": "user-x"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://dingtalk.test")
    gateway = HttpDingTalkGateway(client=client)

    identity = gateway.exchange_code("abc")

    assert identity.tenant_id == "corp-x"
    assert identity.user_id == "user-x"
