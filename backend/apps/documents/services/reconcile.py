"""Storage reconciliation and orphan cleanup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.utils import timezone

from apps.documents.models import FileObject, StorageStatus, UploadSession
from apps.documents.services.ingest import complete_pending_file_activation
from apps.documents.storage.base import FileStorage


@dataclass(frozen=True)
class ReconcileStorage:
    storage: FileStorage
    pending_timeout_minutes: int = 120
    # Callers (e.g. projects domain) supply protected temp relpaths; documents
    # must not import projects models to discover them.
    protected_temp_relpaths: Callable[[], set[str]] | set[str] | None = None

    def execute(self) -> dict[str, int]:
        marked_missing = 0
        cleaned_temp = 0
        pending_swept = 0
        pending_activated = 0
        cutoff = timezone.now() - timedelta(minutes=self.pending_timeout_minutes)

        for file_object in FileObject.objects.filter(storage_status=StorageStatus.ACTIVE):
            path = self.storage.final_path_for(file_object.object_key)
            if not path.exists():
                file_object.storage_status = StorageStatus.MISSING
                file_object.save(update_fields=["storage_status"])
                marked_missing += 1

        for file_object in FileObject.objects.filter(storage_status=StorageStatus.PENDING):
            path = self.storage.final_path_for(file_object.object_key)
            if path.exists():
                complete_pending_file_activation(file_object)
                pending_activated += 1
                continue
            if file_object.created_at < cutoff:
                file_object.storage_status = StorageStatus.MISSING
                file_object.save(update_fields=["storage_status"])
                pending_swept += 1

        for session in UploadSession.objects.filter(
            completed_at__isnull=True, expires_at__lt=cutoff
        ):
            # Never delete temps still claimed by an incomplete upload session
            # that has not expired under the pending timeout window above.
            temp_path = Path(session.temp_path)
            if temp_path.exists() and session.expires_at < cutoff:
                temp_path.unlink()
                cleaned_temp += 1

        protected: set[str] = set()
        if callable(self.protected_temp_relpaths):
            protected = set(self.protected_temp_relpaths())
        elif self.protected_temp_relpaths is not None:
            protected = set(self.protected_temp_relpaths)

        temp_dir = self.storage.temp_dir()
        if temp_dir.exists():
            cutoff_ts = cutoff.timestamp()
            for part in temp_dir.glob("*.part"):
                try:
                    rel = part.name
                    if rel in protected or f"migration/{part.name}" in protected:
                        continue
                    # Skip temps still owned by non-expired incomplete sessions.
                    if UploadSession.objects.filter(
                        temp_path=str(part), completed_at__isnull=True, expires_at__gte=cutoff
                    ).exists():
                        continue
                    if part.stat().st_mtime < cutoff_ts:
                        part.unlink()
                        cleaned_temp += 1
                except OSError:
                    continue
            migration_dir = temp_dir / "migration"
            if migration_dir.exists():
                for part in migration_dir.glob("*.part"):
                    try:
                        rel = f"migration/{part.name}"
                        if rel in protected:
                            continue
                        if part.stat().st_mtime < cutoff_ts:
                            part.unlink()
                            cleaned_temp += 1
                    except OSError:
                        continue

        return {
            "marked_missing": marked_missing,
            "cleaned_temp": cleaned_temp,
            "pending_swept": pending_swept,
            "pending_activated": pending_activated,
        }
