"""Append-only audit event records."""

from __future__ import annotations

import uuid

from django.db import models


class AuditResult(models.TextChoices):
    SUCCESS = "SUCCESS", "Success"
    FAILURE = "FAILURE", "Failure"


class AuditEvent(models.Model):
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    occurred_at = models.DateTimeField()
    actor_user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="audit_events_as_actor",
    )
    acting_roles_snapshot = models.JSONField(default=list)
    action_code = models.CharField(max_length=128)
    resource_type = models.CharField(max_length=64)
    resource_public_id = models.UUIDField(null=True, blank=True)
    result = models.CharField(max_length=16, choices=AuditResult.choices)
    before_summary = models.JSONField(default=dict)
    after_summary = models.JSONField(default=dict)
    reason = models.CharField(max_length=512, blank=True)
    trace_id = models.CharField(max_length=64)
    request_metadata = models.JSONField(default=dict)
    related_snapshot_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_audit_event"
        indexes = [
            models.Index(fields=["occurred_at"]),
            models.Index(fields=["action_code", "occurred_at"]),
            models.Index(fields=["resource_type", "resource_public_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action_code}:{self.event_id}"
