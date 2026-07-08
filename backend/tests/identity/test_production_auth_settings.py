"""Production settings must reject development-only authentication."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_production_settings_reject_dev_login() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SECRET_KEY": "prod-secret",
            "DJANGO_ALLOWED_HOSTS": "example.com",
            "MYSQL_DATABASE": "meridian",
            "MYSQL_USER": "meridian",
            "MYSQL_PASSWORD": "secret",
            "MYSQL_HOST": "db",
            "ENABLE_DEV_LOGIN": "true",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.production"],
        cwd=backend_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ENABLE_DEV_LOGIN" in result.stderr
