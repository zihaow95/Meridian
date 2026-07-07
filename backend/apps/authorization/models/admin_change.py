"""Platform security settings and admin change requests."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class SecuritySetting(PublicIdModel):
    setting_key = models.CharField(max_length=64, unique=True)
    dual_control_enabled = models.BooleanField(default=False)
    version_no = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "authorization_security_setting"

    def __str__(self) -> str:
        return self.setting_key


class AdminChangeStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    APPLIED = "APPLIED", "Applied"
    EXPIRED = "EXPIRED", "Expired"


class AdminChangeRequest(PublicIdModel):
    action_type = models.CharField(max_length=64)
    target_summary = models.JSONField(default=dict)
    proposed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="proposed_admin_changes",
    )
    before_summary = models.JSONField(default=dict)
    after_summary = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=AdminChangeStatus.choices,
        default=AdminChangeStatus.PENDING,
    )
    reviewed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_admin_changes",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_admin_change_request"

    def __str__(self) -> str:
        return f"{self.action_type}:{self.public_id}"
