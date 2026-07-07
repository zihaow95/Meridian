"""External identity bindings and OAuth state."""

from __future__ import annotations

from django.db import models


class IdentityProvider(models.TextChoices):
    DINGTALK = "DINGTALK", "DingTalk"


class BindingStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOKED = "REVOKED", "Revoked"


class IdentityBinding(models.Model):
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="identity_bindings",
    )
    provider = models.CharField(max_length=32, choices=IdentityProvider.choices)
    provider_tenant_id = models.CharField(max_length=128)
    provider_user_id = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=BindingStatus.choices,
        default=BindingStatus.ACTIVE,
    )
    last_authenticated_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_identity_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_tenant_id", "provider_user_id"],
                name="identity_binding_provider_identity_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_user_id}"


class AuthState(models.Model):
    """One-time OAuth state for external authentication callbacks."""

    state_hash = models.CharField(max_length=128, unique=True)
    redirect_path = models.CharField(max_length=512)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity_auth_state"

    def __str__(self) -> str:
        return self.state_hash[:12]
