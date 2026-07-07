"""Deterministic DingTalk gateway for tests."""

from __future__ import annotations

from apps.integrations.dingtalk.contracts import DingTalkIdentity


class FakeDingTalkGateway:
    def __init__(self, *, identities: dict[str, DingTalkIdentity] | None = None) -> None:
        self._identities = identities or {}

    def register(self, code: str, identity: DingTalkIdentity) -> None:
        self._identities[code] = identity

    def exchange_code(self, code: str) -> DingTalkIdentity:
        if code not in self._identities:
            raise KeyError(f"Unknown authorization code: {code}")
        return self._identities[code]

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"/fake-dingtalk/authorize?state={state}&redirect_uri={redirect_uri}"
