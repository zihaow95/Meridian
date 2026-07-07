"""Abstract base models shared across platform and business domains."""

from __future__ import annotations

import uuid

from django.db import models


class PublicIdModel(models.Model):
    """Expose a stable UUID to external callers; internal PK stays BIGINT."""

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    class Meta:
        abstract = True


class OrganizationOwnedModel(PublicIdModel):
    """Every core business row belongs to exactly one organization."""

    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
    )

    class Meta:
        abstract = True
