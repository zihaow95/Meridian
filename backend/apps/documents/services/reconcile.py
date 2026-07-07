"""Storage reconciliation and orphan cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from apps.documents.models import FileObject, StorageStatus, UploadSession
from apps.documents.storage.base import FileStorage


@dataclass(frozen=True)
class ReconcileStorage:
    storage: FileStorage
    pending_timeout_minutes: int = 120

    def execute(self) -> dict[str, int]:
        marked_missing = 0
        cleaned_temp = 0
        cutoff = timezone.now() - timedelta(minutes=self.pending_timeout_minutes)

        for file_object in FileObject.objects.filter(storage_status=StorageStatus.ACTIVE):
            path = self.storage.final_path_for(file_object.object_key)
            if not path.exists():
                file_object.storage_status = StorageStatus.MISSING
                file_object.save(update_fields=["storage_status"])
                marked_missing += 1

        for session in UploadSession.objects.filter(
            completed_at__isnull=True, expires_at__lt=cutoff
        ):
            temp_path = Path(session.temp_path)
            if temp_path.exists():
                temp_path.unlink()
                cleaned_temp += 1

        return {"marked_missing": marked_missing, "cleaned_temp": cleaned_temp}
