"""Controlled document and file object models."""

from __future__ import annotations

from django.db import models

from apps.identity.models.user import User
from apps.platform.models.base import OrganizationOwnedModel, PublicIdModel


class StorageBackend(models.TextChoices):
    NAS_NFS = "NAS_NFS", "NAS NFS"


class StorageStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    MISSING = "MISSING", "Missing"
    QUARANTINED = "QUARANTINED", "Quarantined"


class DocumentSource(models.TextChoices):
    PROJECT = "PROJECT", "Project"
    PRODUCT = "PRODUCT", "Product"
    MIGRATION = "MIGRATION", "Migration"
    INTEGRATION = "INTEGRATION", "Integration"


class DocumentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    VOIDED = "VOIDED", "Voided"
    ARCHIVED = "ARCHIVED", "Archived"


class VersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    LOCKED = "LOCKED", "Locked"
    CONTROLLED = "CONTROLLED", "Controlled"
    RETURNED = "RETURNED", "Returned"
    VOIDED = "VOIDED", "Voided"


class TicketAction(models.TextChoices):
    PREVIEW = "PREVIEW", "Preview"
    DOWNLOAD = "DOWNLOAD", "Download"


class FileObject(OrganizationOwnedModel):
    storage_backend = models.CharField(
        max_length=16,
        choices=StorageBackend.choices,
        default=StorageBackend.NAS_NFS,
    )
    object_key = models.CharField(max_length=512)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    detected_mime_type = models.CharField(max_length=128)
    storage_status = models.CharField(
        max_length=16,
        choices=StorageStatus.choices,
        default=StorageStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents_file_object"
        indexes = [
            models.Index(fields=["storage_status", "created_at"]),
        ]


class Document(OrganizationOwnedModel):
    document_code = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=16, choices=DocumentSource.choices)
    default_sensitivity_level = models.CharField(max_length=32, default="INTERNAL")
    current_version = models.ForeignKey(
        "documents.DocumentVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(
        max_length=16,
        choices=DocumentStatus.choices,
        default=DocumentStatus.ACTIVE,
    )

    class Meta:
        db_table = "documents_document"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "document_code"],
                name="documents_document_org_code_uniq",
            )
        ]


class DocumentVersion(OrganizationOwnedModel):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    file_object = models.ForeignKey(FileObject, on_delete=models.PROTECT, related_name="versions")
    original_filename = models.CharField(max_length=255)
    declared_mime_type = models.CharField(max_length=128)
    detected_mime_type = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16, choices=VersionStatus.choices, default=VersionStatus.DRAFT
    )
    sensitivity_level = models.CharField(max_length=32, default="INTERNAL")
    uploaded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="document_versions_uploaded"
    )
    uploaded_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    controlled_at = models.DateTimeField(null=True, blank=True)
    supersedes_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        db_table = "documents_document_version"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="documents_version_doc_num_uniq",
            )
        ]


class DocumentLink(OrganizationOwnedModel):
    document_version = models.ForeignKey(
        DocumentVersion, on_delete=models.PROTECT, related_name="links"
    )
    linked_type = models.CharField(max_length=64)
    linked_id = models.UUIDField()

    class Meta:
        db_table = "documents_document_link"
        indexes = [
            models.Index(fields=["linked_type", "linked_id"]),
        ]


class UploadSession(PublicIdModel):
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    temp_path = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=255)
    declared_mime_type = models.CharField(max_length=128)
    size_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents_upload_session"


class DownloadTicket(PublicIdModel):
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT)
    action = models.CharField(max_length=16, choices=TicketAction.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "documents_download_ticket"
