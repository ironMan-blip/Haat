from django.db import migrations


class Migration(migrations.Migration):
    """One account per email, case-insensitive, even under parallel sign-ups. Blank emails (older
    accounts, admin-made users) are left out. Fails if duplicate emails already exist: fix those first."""

    dependencies = [
        ("shop", "0010_comment_replies_likes_edits"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE UNIQUE INDEX shop_auth_user_email_ci ON auth_user (UPPER(email)) WHERE email <> ''",
            "DROP INDEX shop_auth_user_email_ci",
        ),
    ]
