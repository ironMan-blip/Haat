from django.db import migrations


class Migration(migrations.Migration):
    """Sign-up refuses "Rafi" when "rafi" exists; this index makes that hold under parallel sign-ups too.
    UPPER() matches what Django's iexact lookup uses on Postgres. Fails if case twins already exist:
    rename one of them first."""

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("shop", "0004_rating_bounds"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE UNIQUE INDEX shop_auth_user_username_ci ON auth_user (UPPER(username))",
            "DROP INDEX shop_auth_user_username_ci",
        ),
    ]
