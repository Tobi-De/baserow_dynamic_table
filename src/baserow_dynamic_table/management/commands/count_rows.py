from baserow_dynamic_table.table.handler import TableHandler
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = (
        "Runs the periodic count rows task without having to wait for the time trigger"
    )

    def handle(self, *args, **options):
        tables_counted = TableHandler.count_rows()
        self.stdout.write(
            self.style.SUCCESS(f"{tables_counted} table(s) have been counted.")
        )
