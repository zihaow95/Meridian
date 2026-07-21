"""Operations domain errors for ingestion and effective values."""

from __future__ import annotations


class UnconfirmedIngestionWarnings(Exception):
    """Raised when WARNING rows exist and confirm_warnings was not granted."""

    def __init__(self, message: str = "WARNING rows require confirm_warnings=True.") -> None:
        super().__init__(message)
        self.message = message
