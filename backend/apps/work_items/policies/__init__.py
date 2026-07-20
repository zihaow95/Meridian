"""Work item authorization identity providers."""

from __future__ import annotations

from apps.work_items.policies.identity_provider import register_providers

__all__ = ["register_providers"]
