"""Create a repeatable demo organization, user, and matching rule."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ledger.models import Organization, ReconciliationRule, User


class Command(BaseCommand):
    help = "Create the LedgerSync demo organization and administrator."

    def handle(self, *args, **options):
        if settings.LEDGERSYNC_PUBLIC_DEMO:
            raise CommandError("Use seed_public_demo for the hosted read-only account.")
        organization, _ = Organization.objects.get_or_create(
            slug="demo-finance",
            defaults={"name": "Demo Finance Co."},
        )
        user, created = User.objects.get_or_create(
            username="admin@example.com",
            defaults={
                "email": "admin@example.com",
                "organization": organization,
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        # Reset only the known demo account so rerunning the command stays easy.
        if created or not user.check_password("Admin12345!"):
            user.set_password("Admin12345!")
        user.organization = organization
        user.role = User.Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.save()
        ReconciliationRule.objects.get_or_create(
            organization=organization,
            name="Default exact reference rule",
            defaults={
                "priority": 1,
                "exact_reference_match": True,
                "date_variance_days": 2,
                "amount_tolerance_percent": "0.00",
                "currency_must_match": True,
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        self.stdout.write("username: admin@example.com")
        self.stdout.write("password: Admin12345!")
