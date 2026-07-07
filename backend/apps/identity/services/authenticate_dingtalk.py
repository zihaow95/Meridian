"""DingTalk authentication orchestration."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from django.utils import timezone

from apps.identity.models.binding import AuthState, BindingStatus, IdentityBinding, IdentityProvider
from apps.identity.models.user import User, UserStatus
from apps.integrations.dingtalk.contracts import DingTalkGateway, DingTalkIdentity
from apps.platform.api.errors import AuthenticationFailedError, UserNotActiveError

if TYPE_CHECKING:
    from django.contrib.sessions.backends.base import SessionBase


class InvalidRedirectPath(Exception):
    pass


def _validate_relative_redirect(path: str) -> str:
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc:
        raise InvalidRedirectPath("Redirect must be a relative in-site path.")
    if not path.startswith("/"):
        raise InvalidRedirectPath("Redirect must start with /.")
    return path


@dataclass(frozen=True)
class DingTalkAuthStart:
    redirect_path: str
    state_ttl: timedelta = timedelta(minutes=10)

    def execute(self) -> tuple[str, str]:
        redirect_path = _validate_relative_redirect(self.redirect_path)
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        AuthState.objects.create(
            state_hash=state_hash,
            redirect_path=redirect_path,
            expires_at=timezone.now() + self.state_ttl,
        )
        return state, redirect_path


@dataclass(frozen=True)
class DingTalkAuthCallback:
    code: str
    state: str
    gateway: DingTalkGateway

    def execute(self) -> tuple[User, str]:
        state_hash = hashlib.sha256(self.state.encode()).hexdigest()
        auth_state = AuthState.objects.filter(state_hash=state_hash, used_at__isnull=True).first()
        if auth_state is None or auth_state.expires_at <= timezone.now():
            raise AuthenticationFailedError(message="Invalid or expired authentication state.")

        auth_state.used_at = timezone.now()
        auth_state.save(update_fields=["used_at"])

        try:
            external_identity = self.gateway.exchange_code(self.code)
        except Exception as exc:
            raise AuthenticationFailedError(message="DingTalk authentication failed.") from exc

        user = self._resolve_user(external_identity)
        if user.status != UserStatus.ACTIVE:
            raise UserNotActiveError()

        IdentityBinding.objects.filter(
            provider=IdentityProvider.DINGTALK,
            provider_tenant_id=external_identity.tenant_id,
            provider_user_id=external_identity.user_id,
            user=user,
            status=BindingStatus.ACTIVE,
        ).update(last_authenticated_at=timezone.now())
        return user, auth_state.redirect_path

    def _resolve_user(self, external_identity: DingTalkIdentity) -> User:
        binding = (
            IdentityBinding.objects.select_related("user")
            .filter(
                provider=IdentityProvider.DINGTALK,
                provider_tenant_id=external_identity.tenant_id,
                provider_user_id=external_identity.user_id,
                status=BindingStatus.ACTIVE,
            )
            .first()
        )
        if binding is None:
            raise AuthenticationFailedError(
                message="No internal user is bound to this DingTalk identity."
            )
        return binding.user


def establish_session(session: SessionBase, user: User) -> None:
    session.cycle_key()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
