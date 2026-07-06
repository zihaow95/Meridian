"""Contract test for the health endpoint.

The endpoint must return a stable structure and must not leak runtime details
(version, database address, paths, secrets). It performs no database access, so
this test does not require the django_db marker.
"""

from __future__ import annotations

from django.test import Client


def test_health_endpoint_exposes_no_sensitive_runtime_details(client: Client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "meridian-api"}
