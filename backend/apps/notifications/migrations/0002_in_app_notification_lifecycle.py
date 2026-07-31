"""Give notifications their own lifecycle and make the todo dedup key real.

Two separate corrections travel together because both rewrite the same tables:

* `Notification.status` used to hold PENDING/DELIVERED/FAILED, which is a channel
  outcome. Existing rows carry no evidence of anyone having read anything, so all
  of them become UNREAD and the migration reports what it saw rather than
  inferring reads from a successful delivery.
* `notifications_todo_open_dedup_uniq` was conditional, which MySQL never
  created (W036). Duplicated open todos may therefore already exist; the
  migration refuses to continue instead of picking a survivor on its own.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

_LEGACY_STATUS_LABELS = ("PENDING", "DELIVERED", "FAILED")


def reset_notification_lifecycle(apps, schema_editor):
    """Move every existing notification to UNREAD and report the old spread."""

    Notification = apps.get_model("notifications", "Notification")
    Delivery = apps.get_model("notifications", "Delivery")

    counts = {
        label: Notification.objects.filter(status=label).count()
        for label in _LEGACY_STATUS_LABELS
    }
    total = sum(counts.values())
    if not total:
        return

    with_in_app = (
        Notification.objects.filter(status__in=_LEGACY_STATUS_LABELS)
        .filter(pk__in=Delivery.objects.filter(channel="IN_APP").values("notification_id"))
        .count()
    )
    Notification.objects.filter(status__in=_LEGACY_STATUS_LABELS).update(status="UNREAD")

    print(
        "\nnotifications.0002: moved "
        + ", ".join(f"{label}={counts[label]}" for label in _LEGACY_STATUS_LABELS)
        + f" (total {total}) to UNREAD. {with_in_app} of them had an IN_APP delivery; "
        "a delivery is not a read, so no row was marked READ or CLOSED."
    )


def refuse_duplicate_open_todos(apps, schema_editor):
    """Stop if the never-created constraint already allowed duplicates through.

    Runs before any DDL so a stop leaves the schema exactly as it was.
    """

    Todo = apps.get_model("notifications", "Todo")
    duplicates = list(
        Todo.objects.filter(status="OPEN")
        .values("assignee_id", "dedup_key")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
        .order_by("assignee_id", "dedup_key")
    )
    if not duplicates:
        return

    detail = "; ".join(
        f"assignee={row['assignee_id']} dedup_key={row['dedup_key']} count={row['total']}"
        for row in duplicates
    )
    raise RuntimeError(
        "Duplicate open todos exist, so the open-dedup uniqueness cannot be "
        "enforced without discarding a work fact. Settle the extras by hand, "
        f"then re-run this migration. Offenders: {detail}"
    )


def occupy_open_todo_sentinel(apps, schema_editor):
    Todo = apps.get_model("notifications", "Todo")
    Todo.objects.filter(status="OPEN").update(open_slot=1)
    Todo.objects.exclude(status="OPEN").update(open_slot=None)


class Migration(migrations.Migration):

    dependencies = [
        ('configuration', '0005_seed_phase6_definitions'),
        ('identity', '0002_remove_user_identity_user_org_employee_no_uniq_and_more'),
        ('notifications', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(refuse_duplicate_open_todos, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='todo',
            name='notifications_todo_open_dedup_uniq',
        ),
        migrations.AddField(
            model_name='notification',
            name='category',
            field=models.CharField(blank=True, choices=[('ACTION_REQUIRED', 'Action required'), ('DEADLINE', 'Deadline'), ('BUSINESS_ALERT', 'Business alert'), ('PROCESS_RESULT', 'Process result'), ('SYSTEM_FAILURE', 'System failure'), ('INFORMATION', 'Information')], max_length=32),
        ),
        migrations.AddField(
            model_name='notification',
            name='close_reason',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='notification',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='level',
            field=models.CharField(blank=True, choices=[('URGENT', 'Urgent'), ('IMPORTANT', 'Important'), ('NORMAL', 'Normal')], max_length=16),
        ),
        migrations.AddField(
            model_name='notification',
            name='policy_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='notification',
            name='policy_version',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='policy_notifications', to='configuration.configurationversion'),
        ),
        migrations.AddField(
            model_name='notification',
            name='read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='template_version',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='notifications', to='configuration.configurationversion'),
        ),
        migrations.AddField(
            model_name='todo',
            name='open_slot',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        # Rewrite the old channel-shaped values before the column is narrowed to
        # the lifecycle choices.
        migrations.RunPython(reset_notification_lifecycle, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='notification',
            name='status',
            field=models.CharField(choices=[('UNREAD', 'Unread'), ('READ', 'Read'), ('CLOSED', 'Closed')], default='UNREAD', max_length=16),
        ),
        migrations.RunPython(occupy_open_todo_sentinel, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'status'], name='notificatio_recipie_e285de_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'category', 'level'], name='notificatio_recipie_b003b1_idx'),
        ),
        migrations.AddConstraint(
            model_name='todo',
            constraint=models.UniqueConstraint(fields=('assignee', 'dedup_key', 'open_slot'), name='notifications_todo_open_dedup_uniq'),
        ),
    ]
