"""Stage gate authorization providers."""

from __future__ import annotations

from apps.stage_gates.policies.identity_provider import register_providers

__all__ = ["register_providers"]
