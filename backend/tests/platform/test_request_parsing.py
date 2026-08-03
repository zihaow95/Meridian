"""Strict boolean parsing for loosely typed HTTP clients."""

from __future__ import annotations

import pytest

from apps.platform.api.errors import ValidationFailedError
from apps.platform.api.request_parsing import parse_request_bool


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("FALSE", False),
        ("0", False),
        ("1", True),
        (0, False),
        (1, True),
    ],
)
def test_parse_request_bool_accepts_canonical_forms(raw, expected) -> None:
    assert parse_request_bool(raw, field="passed") is expected


def test_parse_request_bool_rejects_ambiguous_truthy_strings() -> None:
    with pytest.raises(ValidationFailedError):
        parse_request_bool("falsey", field="passed")
