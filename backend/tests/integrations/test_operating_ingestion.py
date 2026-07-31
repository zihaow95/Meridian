"""Unified operating ingestion batches: API, CSV, Excel, and MANUAL."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone
from openpyxl import Workbook

from apps.documents.models import StorageStatus, VersionStatus
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.integrations.models import (
    DataSourceType,
    IngestionBatchStatus,
    IngestionRowStatus,
)
from apps.integrations.services.data_sources import ConfigureOperatingDataSource
from apps.integrations.services.ingestion import (
    CreateIngestionBatch,
    ValidateIngestionBatch,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    SKU,
    ChannelConfiguration,
    ChannelStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
    SKUStatus,
)
from tests.products.document_factories import build_controlled_document_version


@pytest.fixture
def ops_department(organization: Organization) -> Department:
    return Department.objects.create(
        organization=organization,
        department_code="OPS-ING",
        name="Operations Ingestion",
        status=DepartmentStatus.ACTIVE,
        valid_from=timezone.now(),
    )


@pytest.fixture
def sku_channel(organization: Organization, active_user: User) -> tuple[SKU, ChannelConfiguration]:
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-ING",
        name="Ingestion yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Launch",
        status=ProductVersionStatus.EFFECTIVE,
        published_at=timezone.now(),
        published_by=active_user,
    )
    sku = SKU.objects.create(
        organization=organization,
        product_version=version,
        sku_code="SKU-READY",
        name="Cup",
        specification="120g",
        status=SKUStatus.ACTIVE,
    )
    channel = ChannelConfiguration.objects.create(
        organization=organization,
        sku=sku,
        channel_code="TMALL",
        configuration_version=1,
        channel_status=ChannelStatus.ON_SALE,
    )
    return sku, channel


def _mapping_content(**overrides) -> dict:
    content = {
        "source_priority": 10,
        "mapping_rules": [
            {"external_field": "sku_code", "internal_field": "sku_code"},
            {"external_field": "channel_code", "internal_field": "channel_code"},
            {"external_field": "sales_amount", "internal_field": "numeric_value"},
            {"external_field": "metric_code", "internal_field": "metric_code"},
            {"external_field": "period_start", "internal_field": "period_start"},
            {"external_field": "period_end", "internal_field": "period_end"},
            {"external_field": "period_granularity", "internal_field": "period_granularity"},
            {"external_field": "unit", "internal_field": "unit"},
            {"external_field": "currency", "internal_field": "currency"},
            {"external_field": "external_record_key", "internal_field": "external_record_key"},
            {"external_field": "source_timestamp", "internal_field": "source_timestamp"},
        ],
        "reasonable_ranges": {"sales_amount": {"min": "0", "max": "1000000"}},
    }
    content.update(overrides)
    return content


def _configure_source(
    *,
    user: User,
    department: Department,
    grant_action,
    source_code: str,
    source_type: str,
):
    grant_action(user, "data_source.configure", "data_source")
    grant_action(user, "configuration.version.publish", "configuration.version")
    return ConfigureOperatingDataSource(
        context=CommandContext.for_actor(user),
        source_code=source_code,
        name=source_code,
        source_type=source_type,
        owner_department_public_id=department.public_id,
        sensitivity_level="SENSITIVE_CONTROLLED",
        mapping_content=_mapping_content(),
    ).execute()


def _row(**overrides) -> dict:
    base = {
        "external_record_key": "ERP-001",
        "sku_code": "SKU-READY",
        "channel_code": "TMALL",
        "metric_code": "GROSS_SALES",
        "period_granularity": "MONTH",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "sales_amount": "1250.50",
        "unit": "CNY",
        "currency": "CNY",
        "source_timestamp": "2026-02-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


def _write_controlled_csv(*, organization, user, rows: list[dict], document_code: str):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    content = buffer.getvalue().encode("utf-8")
    version = build_controlled_document_version(
        organization=organization,
        uploaded_by=user,
        document_code=document_code,
    )
    version.original_filename = f"{document_code}.csv"
    version.declared_mime_type = "text/csv"
    version.detected_mime_type = "text/csv"
    version.save(
        update_fields=[
            "original_filename",
            "declared_mime_type",
            "detected_mime_type",
        ]
    )
    path = get_file_storage().final_path_for(version.file_object.object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return version


def _write_controlled_xlsx(*, organization, user, rows: list[dict], document_code: str):
    workbook = Workbook()
    sheet = workbook.active
    headers = list(rows[0].keys())
    sheet.append(headers)
    for row in rows:
        sheet.append([row[h] for h in headers])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()
    version = build_controlled_document_version(
        organization=organization,
        uploaded_by=user,
        document_code=document_code,
    )
    version.original_filename = f"{document_code}.xlsx"
    version.declared_mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    version.detected_mime_type = version.declared_mime_type
    version.save(
        update_fields=[
            "original_filename",
            "declared_mime_type",
            "detected_mime_type",
        ]
    )
    path = get_file_storage().final_path_for(version.file_object.object_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return version


@pytest.mark.django_db(transaction=True)
def test_api_csv_excel_and_manual_enter_same_batch_pipeline(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    del sku_channel
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    grant_action(active_user, "ingestion_batch.confirm", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)

    api_source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="API_SALES",
        source_type=DataSourceType.API,
    )
    file_source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="FILE_SALES",
        source_type=DataSourceType.FILE,
    )
    manual_source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="MANUAL_SALES",
        source_type=DataSourceType.MANUAL,
    )

    api_batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=api_source.public_id,
        batch_key="API-2026-01",
        source_type=DataSourceType.API,
        rows=[_row(external_record_key="API-1")],
    ).execute()
    csv_version = _write_controlled_csv(
        organization=active_user.organization,
        user=active_user,
        rows=[_row(external_record_key="CSV-1")],
        document_code="OPS-CSV-1",
    )
    csv_batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=file_source.public_id,
        batch_key="CSV-2026-01",
        source_type=DataSourceType.FILE,
        input_file_version_public_id=csv_version.public_id,
    ).execute()
    xlsx_version = _write_controlled_xlsx(
        organization=active_user.organization,
        user=active_user,
        rows=[_row(external_record_key="XLSX-1")],
        document_code="OPS-XLSX-1",
    )
    xlsx_batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=file_source.public_id,
        batch_key="XLSX-2026-01",
        source_type=DataSourceType.FILE,
        input_file_version_public_id=xlsx_version.public_id,
    ).execute()
    manual_batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=manual_source.public_id,
        batch_key="MANUAL-2026-01",
        source_type=DataSourceType.MANUAL,
        rows=[_row(external_record_key="MANUAL-1")],
    ).execute()

    for batch in (api_batch, csv_batch, xlsx_batch, manual_batch):
        assert batch.status == IngestionBatchStatus.RECEIVED
        assert batch.rows.count() == 1
        ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()
        batch.refresh_from_db()
        assert batch.status == IngestionBatchStatus.READY
        row = batch.rows.get()
        assert row.status == IngestionRowStatus.VALID
        assert row.period_granularity == "MONTH"
        assert row.period_start == date(2026, 1, 1)
        assert row.period_end == date(2026, 1, 31)
        assert row.unit == "CNY"
        assert row.currency == "CNY"
        assert row.external_record_key in {"API-1", "CSV-1", "XLSX-1", "MANUAL-1"}
        assert row.source_timestamp is not None
        assert row.numeric_value == Decimal("1250.50")


@pytest.mark.django_db(transaction=True)
def test_file_batch_requires_active_controlled_document_version(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="FILE_ONLY",
        source_type=DataSourceType.FILE,
    )
    version = build_controlled_document_version(
        organization=active_user.organization,
        uploaded_by=active_user,
        document_code="OPS-INACTIVE",
    )
    version.file_object.storage_status = StorageStatus.MISSING
    version.file_object.save(update_fields=["storage_status"])
    version.status = VersionStatus.DRAFT
    version.save(update_fields=["status"])

    with pytest.raises(ValidationFailedError):
        CreateIngestionBatch(
            context=CommandContext.for_actor(active_user),
            source_public_id=source.public_id,
            batch_key="BAD-FILE",
            source_type=DataSourceType.FILE,
            input_file_version_public_id=version.public_id,
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_structure_errors_unmapped_and_duplicates_block_rows_range_is_warning(
    active_user: User,
    ops_department: Department,
    sku_channel,
    grant_action,
) -> None:
    del sku_channel
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)
    source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="VALIDATE_SALES",
        source_type=DataSourceType.API,
    )
    batch = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="VALIDATE-1",
        source_type=DataSourceType.API,
        rows=[
            _row(external_record_key="OK-1"),
            _row(external_record_key="DUP-1"),
            _row(external_record_key="DUP-1", sales_amount="99"),
            _row(external_record_key="BAD-SKU", sku_code="MISSING"),
            _row(external_record_key="RANGE-1", sales_amount="9999999"),
            _row(external_record_key="BAD-UNIT", unit="", currency=""),
        ],
    ).execute()
    validated = ValidateIngestionBatch(context=ctx, batch_public_id=batch.public_id).execute()

    by_key = {row.external_record_key: row for row in validated.rows.all()}
    assert by_key["OK-1"].status == IngestionRowStatus.VALID
    assert by_key["DUP-1"].status == IngestionRowStatus.ERROR
    assert by_key["BAD-SKU"].status == IngestionRowStatus.UNMAPPED
    assert by_key["RANGE-1"].status == IngestionRowStatus.WARNING
    assert by_key["BAD-UNIT"].status == IngestionRowStatus.ERROR
    validated.refresh_from_db()
    assert validated.error_count >= 3
    assert validated.warning_count >= 1
    assert validated.status == IngestionBatchStatus.READY


@pytest.mark.django_db(transaction=True)
def test_source_and_batch_key_are_idempotent(
    active_user: User,
    ops_department: Department,
    grant_action,
) -> None:
    grant_action(active_user, "ingestion_batch.create", "ingestion_batch")
    ctx = CommandContext.for_actor(active_user)
    source = _configure_source(
        user=active_user,
        department=ops_department,
        grant_action=grant_action,
        source_code="IDEM_SALES",
        source_type=DataSourceType.API,
    )
    first = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="IDEM-KEY",
        source_type=DataSourceType.API,
        rows=[_row()],
    ).execute()
    second = CreateIngestionBatch(
        context=ctx,
        source_public_id=source.public_id,
        batch_key="IDEM-KEY",
        source_type=DataSourceType.API,
        rows=[_row(external_record_key="OTHER")],
    ).execute()
    assert first.public_id == second.public_id
    assert first.rows.count() == 1
