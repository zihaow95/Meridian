"""DingTalk notification channel."""

from __future__ import annotations

from typing import Protocol


class DingTalkNotifier(Protocol):
    def send_work_notification(self, *, user_id: int, body: str, url: str) -> str: ...


class DingTalkNotificationGateway:
    def __init__(self, notifier: DingTalkNotifier | None = None) -> None:
        from django.conf import settings

        self._notifier = notifier or getattr(settings, "DINGTALK_NOTIFIER", None)

    def send(self, *, recipient_user_id: int, summary: str, deep_link: str) -> str:
        if self._notifier is None:
            raise RuntimeError("DingTalk notifier is not configured.")
        return self._notifier.send_work_notification(
            user_id=recipient_user_id,
            body=summary,
            url=deep_link,
        )
