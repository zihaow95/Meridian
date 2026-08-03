"""Make non-empty employee_no unique per organization on MySQL.

The conditional UniqueConstraint was never created (W036). Existing duplicates
of a filled employee_no must be settled by hand before this migration continues;
empty employee numbers stay free to coexist via a nullable sentinel.
"""

from django.db import migrations, models


def refuse_duplicate_employee_numbers(apps, schema_editor):
    """Stop if non-empty employee numbers already collide.

    Runs before any DDL so a stop leaves the schema exactly as it was.
    """

    User = apps.get_model("identity", "User")
    duplicates = list(
        User.objects.exclude(employee_no="")
        .values("organization_id", "employee_no")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
        .order_by("organization_id", "employee_no")
    )
    if not duplicates:
        return

    detail = "; ".join(
        f"organization={row['organization_id']} employee_no={row['employee_no']} "
        f"count={row['total']}"
        for row in duplicates
    )
    raise RuntimeError(
        "Duplicate non-empty employee_no values exist, so the uniqueness cannot "
        "be enforced without discarding an identity fact. Settle the extras by "
        f"hand, then re-run this migration. Offenders: {detail}"
    )


def occupy_employee_no_sentinel(apps, schema_editor):
    User = apps.get_model("identity", "User")
    User.objects.exclude(employee_no="").update(employee_no_slot=1)
    User.objects.filter(employee_no="").update(employee_no_slot=None)


class Migration(migrations.Migration):

    dependencies = [
        ("identity", "0002_remove_user_identity_user_org_employee_no_uniq_and_more"),
    ]

    operations = [
        migrations.RunPython(refuse_duplicate_employee_numbers, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="user",
            name="identity_user_org_employee_no_uniq",
        ),
        migrations.AddField(
            model_name="user",
            name="employee_no_slot",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(occupy_employee_no_sentinel, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                fields=("organization", "employee_no", "employee_no_slot"),
                name="identity_user_org_employee_no_uniq",
            ),
        ),
    ]
