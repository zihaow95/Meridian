"""HTTP-backed DingTalk gateway using httpx."""

from __future__ import annotations

import httpx

from apps.integrations.dingtalk.contracts import DingTalkIdentity


class HttpDingTalkGateway:
    def __init__(self, *, client: httpx.Client) -> None:
        self._client = client

    def exchange_code(self, code: str) -> DingTalkIdentity:
        response = self._client.post("/oauth/token", json={"code": code})
        response.raise_for_status()
        payload = response.json()
        return DingTalkIdentity(
            tenant_id=str(payload["tenant_id"]),
            user_id=str(payload["user_id"]),
        )
