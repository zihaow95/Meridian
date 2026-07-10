"""Legacy product import CSV template definition and parsing."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from typing import Any

IMPORT_TEMPLATE_VERSION = "legacy-product-v1"

REQUIRED_COLUMNS = ("name", "category_code")
OPTIONAL_COLUMNS = (
    "business_no",
    "external_id",
    "brand_code",
    "sku_code",
    "barcode",
    "specification",
    "net_content_value",
    "net_content_unit",
)
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


@dataclass(frozen=True)
class ParsedImportRow:
    row_number: int
    raw_row_digest: str
    normalized_payload: dict[str, Any]
    validation_errors: list[dict[str, str]]


def digest_row(*, row_number: int, values: dict[str, str]) -> str:
    payload = f"{row_number}:{sorted(values.items())}".encode()
    return hashlib.sha256(payload).hexdigest()


def parse_import_csv(*, content: str) -> list[ParsedImportRow]:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        return []
    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    rows: list[ParsedImportRow] = []
    for index, raw in enumerate(reader, start=1):
        values = {
            column: (raw.get(column) or "").strip() for column in ALL_COLUMNS if column in raw
        }
        errors: list[dict[str, str]] = []
        if not values.get("name"):
            errors.append({"field": "name", "message": "Name is required."})
        if not values.get("category_code"):
            errors.append({"field": "category_code", "message": "Category code is required."})
        rows.append(
            ParsedImportRow(
                row_number=index,
                raw_row_digest=digest_row(row_number=index, values=values),
                normalized_payload=values,
                validation_errors=errors,
            )
        )
    return rows


def sample_import_csv() -> str:
    return (
        "name,category_code,business_no,brand_code,sku_code,barcode,specification\n"
        "Legacy yogurt,YOGURT,LEG-001,BRAND-A,SKU-LEG-001,6900000000001,120g\n"
        "Legacy milk,DAIRY,LEG-002,BRAND-B,SKU-LEG-002,6900000000002,250ml\n"
    )
