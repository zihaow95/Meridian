from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_emergency_confirmation_evidence"),
    ]

    operations = [
        migrations.AddField(
            model_name="migrationbaseline",
            name="history_deliverables",
            field=models.JSONField(default=list),
        ),
    ]
