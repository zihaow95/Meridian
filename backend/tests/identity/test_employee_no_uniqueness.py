"""Non-empty employee_no must be unique per organization on MySQL.

The conditional UniqueConstraint was never created (W036). Uniqueness is
re-expressed with a nullable sentinel so empty employee numbers stay free to
collide while a filled number cannot be claimed twice.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, migrations, transaction

from apps.identity.models.user import User, UserStatus

employee_no_migration = importlib.import_module(
    "apps.identity.migrations.0003_employee_no_unique_slot"
)

pytestmark = pytest.mark.django_db


def test_a_non_empty_employee_no_occupies_the_sentinel(organization) -> None:
    user = User.objects.create_user(
        organization=organization,
        display_name="Pilot One",
        employee_no="E-1001",
        status=UserStatus.ACTIVE,
    )

    assert user.employee_no_slot == 1


def test_an_empty_employee_no_leaves_the_sentinel_free(organization) -> None:
    first = User.objects.create_user(
        organization=organization, display_name="No Number A", employee_no=""
    )
    second = User.objects.create_user(
        organization=organization, display_name="No Number B", employee_no=""
    )

    assert first.employee_no_slot is None
    assert second.employee_no_slot is None


def test_database_refuses_a_second_user_with_the_same_employee_no(organization) -> None:
    User.objects.create_user(
        organization=organization,
        display_name="Pilot One",
        employee_no="E-1001",
        status=UserStatus.ACTIVE,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(
            organization=organization,
            display_name="Pilot Twin",
            employee_no="E-1001",
            status=UserStatus.ACTIVE,
        )


def test_clearing_employee_no_releases_the_number_for_reuse(organization) -> None:
    user = User.objects.create_user(
        organization=organization,
        display_name="Pilot One",
        employee_no="E-1001",
        status=UserStatus.ACTIVE,
    )
    user.employee_no = ""
    user.save(update_fields=["employee_no", "employee_no_slot", "updated_at"])

    replacement = User.objects.create_user(
        organization=organization,
        display_name="Pilot Two",
        employee_no="E-1001",
        status=UserStatus.ACTIVE,
    )

    assert replacement.employee_no_slot == 1


def test_the_migration_refuses_duplicate_employee_numbers_instead_of_picking(
    organization,
) -> None:
    for index in range(2):
        User.objects.create_user(
            organization=organization,
            display_name=f"Dup {index}",
            employee_no="",
            status=UserStatus.ACTIVE,
        )
    User.objects.filter(organization=organization).update(
        employee_no="E-DUP", employee_no_slot=None
    )

    with pytest.raises(RuntimeError) as excinfo:
        employee_no_migration.refuse_duplicate_employee_numbers(django_apps, None)

    assert "E-DUP" in str(excinfo.value)


def test_the_duplicate_guard_runs_before_schema_changes() -> None:
    operations = employee_no_migration.Migration.operations
    guard_index = next(
        index
        for index, operation in enumerate(operations)
        if isinstance(operation, migrations.RunPython)
        and operation.code is employee_no_migration.refuse_duplicate_employee_numbers
    )
    first_schema_index = next(
        index
        for index, operation in enumerate(operations)
        if not isinstance(operation, migrations.RunPython)
    )

    assert guard_index < first_schema_index
