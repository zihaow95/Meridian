"""App configuration for platform-level infrastructure endpoints."""

from __future__ import annotations

from django.apps import AppConfig


class PlatformConfig(AppConfig):
    name = "apps.platform"
    label = "platform"
