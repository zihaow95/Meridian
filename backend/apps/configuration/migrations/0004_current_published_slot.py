"""Carry "one published version per definition" in a MySQL-enforceable slot."""

from django.conf import settings
from django.db import migrations, models
from django.db.models import Count


def reject_duplicate_published_versions(apps, schema_editor) -> None:
    """Fail before any DDL: MySQL cannot roll back a half-applied migration."""
    version_model = apps.get_model("configuration", "ConfigurationVersion")
    duplicates = (
        version_model.objects.filter(status="PUBLISHED")
        .values("definition_id")
        .annotate(published_count=Count("id"))
        .filter(published_count__gt=1)
        .order_by("definition_id")
    )
    conflicts = [
        f"definition_id={row['definition_id']} has {row['published_count']} PUBLISHED versions"
        for row in duplicates
    ]
    if conflicts:
        raise RuntimeError(
            "Cannot backfill ConfigurationVersion.current_published_slot: "
            "more than one PUBLISHED version exists for "
            f"{len(conflicts)} definition(s): {'; '.join(conflicts)}. "
            "Resolve which version is current before applying this migration."
        )


def occupy_slot_for_published_versions(apps, schema_editor) -> None:
    version_model = apps.get_model("configuration", "ConfigurationVersion")
    version_model.objects.filter(status="PUBLISHED").update(current_published_slot=1)


def release_slot(apps, schema_editor) -> None:
    version_model = apps.get_model("configuration", "ConfigurationVersion")
    version_model.objects.update(current_published_slot=None)


def noop(apps, schema_editor) -> None:
    return None


class Migration(migrations.Migration):

    dependencies = [
        ('configuration', '0003_seed_operating_source_mapping_definition'),
        ('identity', '0002_remove_user_identity_user_org_employee_no_uniq_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(reject_duplicate_published_versions, noop),
        migrations.AddField(
            model_name='configurationversion',
            name='current_published_slot',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(occupy_slot_for_published_versions, release_slot),
        migrations.AddConstraint(
            model_name='configurationversion',
            constraint=models.UniqueConstraint(fields=('definition', 'current_published_slot'), name='configuration_version_published_slot_uniq'),
        ),
    ]
