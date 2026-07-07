"""DingTalk integration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DingTalkIdentity:
    tenant_id: str
    user_id: str


class DingTalkGateway(Protocol):
    def exchange_code(self, code: str) -> DingTalkIdentity:
        """Exchange an authorization code for a DingTalk identity."""

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Build the browser redirect URL for the OAuth authorize step."""
