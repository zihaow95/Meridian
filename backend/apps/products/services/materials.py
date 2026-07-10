"""Product material attachment and controlled document validation."""

from __future__ import annotations

from apps.documents.models import VersionStatus
from apps.products.models import ProductMaterial

_PUBLISHABLE_VERSION_STATUSES = frozenset(
    {VersionStatus.LOCKED, VersionStatus.CONTROLLED},
)


def is_controlled_document_version(document_version_id: int) -> bool:
    from apps.documents.models import DocumentVersion

    status = (
        DocumentVersion.objects.filter(id=document_version_id)
        .values_list("status", flat=True)
        .first()
    )
    return status in _PUBLISHABLE_VERSION_STATUSES


def validate_material_for_publication(material: ProductMaterial) -> str | None:
    if not is_controlled_document_version(material.document_version_id):
        return "PRODUCT_MATERIAL_NOT_CONTROLLED"
    return None
