# Generated manually for MySQL-safe RoleAssignment uniqueness.

from django.conf import settings
from django.db import migrations, models
from django.db.models import Count, Min
from django.utils import timezone


def backfill_scope_key(apps, schema_editor) -> None:
    RoleAssignment = apps.get_model("authorization", "RoleAssignment")
    User = apps.get_model("identity", "User")
    user_org = dict(User.objects.values_list("id", "organization_id"))

    for assignment in RoleAssignment.objects.all().iterator():
        scope_id = assignment.scope_id
        if scope_id is None:
            if assignment.scope_type == "ORGANIZATION":
                scope_id = user_org.get(assignment.user_id)
            if scope_id is None:
                raise RuntimeError(
                    "Cannot backfill RoleAssignment.scope_id for "
                    f"id={assignment.id} scope_type={assignment.scope_type}"
                )
            assignment.scope_id = scope_id
        assignment.scope_key = f"{assignment.scope_type}:{scope_id}"
        if assignment.status != "ACTIVE" or assignment.effective_to is not None:
            assignment.active_slot = None
        elif assignment.active_slot is None:
            assignment.active_slot = 1
        assignment.save(update_fields=["scope_id", "scope_key", "active_slot"])

    # After normalization, NULL and explicit org scopes can collide on scope_key.
    now = timezone.now()
    duplicates = (
        RoleAssignment.objects.filter(active_slot=1)
        .values("user_id", "role_id", "scope_type", "scope_key")
        .annotate(n=Count("id"), keep_id=Min("id"))
        .filter(n__gt=1)
    )
    for row in duplicates:
        RoleAssignment.objects.filter(
            user_id=row["user_id"],
            role_id=row["role_id"],
            scope_type=row["scope_type"],
            scope_key=row["scope_key"],
            active_slot=1,
        ).exclude(id=row["keep_id"]).update(
            active_slot=None,
            status="INACTIVE",
            effective_to=now,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("authorization", "0010_role_assignment_active_slot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="roleassignment",
            name="authorization_role_assignment_active_slot_uniq",
        ),
        migrations.AddField(
            model_name="roleassignment",
            name="scope_key",
            field=models.CharField(blank=True, default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_scope_key, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="roleassignment",
            name="scope_id",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="roleassignment",
            name="scope_key",
            field=models.CharField(max_length=64),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.UniqueConstraint(
                fields=("user", "role", "scope_type", "scope_key", "active_slot"),
                name="authorization_role_assignment_scope_key_slot_uniq",
            ),
        ),
    ]
