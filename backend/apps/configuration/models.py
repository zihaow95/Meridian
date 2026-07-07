"""Immutable configuration versions and reference snapshots."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import models

from apps.identity.models.user import User
from apps.platform.models.base import OrganizationOwnedModel


class ConfigurationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    VALIDATING = "VALIDATING", "Validating"
    PUBLISHED = "PUBLISHED", "Published"
    FAILED = "FAILED", "Failed"
    RETIRED = "RETIRED", "Retired"


class PublishedConfigurationImmutable(Exception):
    pass


class ConfigurationDefinition(OrganizationOwnedModel):
    definition_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta:
        db_table = "configuration_definition"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "definition_code"],
                name="configuration_definition_org_code_uniq",
            )
        ]

    def __str__(self) -> str:
        return self.definition_code


class ConfigurationVersion(OrganizationOwnedModel):
    definition = models.ForeignKey(
        ConfigurationDefinition,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        choices=ConfigurationStatus.choices,
        default=ConfigurationStatus.DRAFT,
    )
    content_json = models.JSONField(default=dict)
    content_digest = models.CharField(max_length=64, blank=True)
    scope_json = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="configuration_versions_created",
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="configuration_versions_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    diff_summary = models.JSONField(default=dict)
    validation_errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "configuration_version"
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version_number"],
                name="configuration_version_def_num_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["definition", "status"]),
        ]

    def replace_content(self, content: dict) -> None:
        if self.status == ConfigurationStatus.PUBLISHED:
            raise PublishedConfigurationImmutable("Published configuration cannot be edited.")
        self.content_json = content
        self.content_digest = compute_content_digest(content)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.status == ConfigurationStatus.PUBLISHED and self.pk:
            previous = (
                ConfigurationVersion.objects.filter(pk=self.pk).values("content_json").first()
            )
            if previous and previous["content_json"] != self.content_json:
                raise PublishedConfigurationImmutable("Published configuration cannot be edited.")
        if not self.content_digest and self.content_json:
            self.content_digest = compute_content_digest(self.content_json)
        super().save(*args, **kwargs)


class ConfigurationSnapshot(OrganizationOwnedModel):
    version = models.ForeignKey(
        ConfigurationVersion,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    content_copy = models.JSONField()
    content_hash = models.CharField(max_length=64)
    reference_type = models.CharField(max_length=64)
    reference_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "configuration_snapshot"
        indexes = [
            models.Index(fields=["reference_type", "reference_id"]),
        ]


def compute_content_digest(content: dict) -> str:
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
