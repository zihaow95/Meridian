"""Bind major gate decisions to the locked FIRST_LAUNCH submission."""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("stage_gates", "0004_first_launch_nullable_final"),
    ]

    operations = [
        migrations.AddField(
            model_name="majorgatedecision",
            name="submission",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="major_decisions",
                to="stage_gates.gatesubmission",
            ),
        ),
    ]
