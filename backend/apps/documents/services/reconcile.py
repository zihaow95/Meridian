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
        pending_swept = 0
        cutoff = timezone.now() - timedelta(minutes=self.pending_timeout_minutes)

        for file_object in FileObject.objects.filter(storage_status=StorageStatus.ACTIVE):
            path = self.storage.final_path_for(file_object.object_key)
            if not path.exists():
                file_object.storage_status = StorageStatus.MISSING
                file_object.save(update_fields=["storage_status"])
                marked_missing += 1

        # Compensate staged objects whose activation never completed (e.g. the
        # storage move failed after the staging transaction committed). Past the
        # timeout, a PENDING object without a backing file is surfaced as MISSING
        # rather than lingering silently.
        for file_object in FileObject.objects.filter(
            storage_status=StorageStatus.PENDING, created_at__lt=cutoff
        ):
            path = self.storage.final_path_for(file_object.object_key)
            if not path.exists():
                file_object.storage_status = StorageStatus.MISSING
                file_object.save(update_fields=["storage_status"])
                pending_swept += 1

        for session in UploadSession.objects.filter(
            completed_at__isnull=True, expires_at__lt=cutoff
        ):
            temp_path = Path(session.temp_path)
            if temp_path.exists():
                temp_path.unlink()
                cleaned_temp += 1

        # Remove orphaned staging payloads left behind by aborted ingests.
        temp_dir = self.storage.temp_dir()
        if temp_dir.exists():
            cutoff_ts = cutoff.timestamp()
            for part in temp_dir.glob("*.part"):
                try:
                    if part.stat().st_mtime < cutoff_ts:
                        part.unlink()
                        cleaned_temp += 1
                except OSError:
                    continue

        return {
            "marked_missing": marked_missing,
            "cleaned_temp": cleaned_temp,
            "pending_swept": pending_swept,
        }
