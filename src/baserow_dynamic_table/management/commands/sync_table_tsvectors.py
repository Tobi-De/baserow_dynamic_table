import sys

from baserow_dynamic_table.search.exceptions import (
    PostgresFullTextSearchDisabledException,
)
from baserow_dynamic_table.search.handler import SearchHandler
from baserow_dynamic_table.table.handler import TableHandler
from baserow_dynamic_table.table.models import Table
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Given a table ID, this command will ensure all TSV columns are created for it"
        ". This will allow it to be indexed and searched against."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "table_id",
            type=int,
            help="The ID of the table to create a tsvector columns for.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        table_id = options["table_id"]
        try:
            table = TableHandler().get_table_for_update(table_id)
        except Table.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"The table with id {table_id} was not found.")
            )
            sys.exit(1)
        try:
            SearchHandler.sync_tsvector_columns(table)
            self.stdout.write(
                self.style.SUCCESS(
                    "The tsvector columns were  been successfully created, "
                    "the next step is to update tsvectors with data. "
                    "This can be done with: "
                    f"./baserow_dynamic_table_dynamic_table_dynamic_table update_table_tsvectors {table_id}"
                )
            )
        except PostgresFullTextSearchDisabledException:
            self.stdout.write(
                self.style.ERROR(
                    "Your baserow_dynamic_table_dynamic_table_dynamic_table installation has Postgres full-text"
                    "search disabled. To use full-text, ensure that"
                    "baserow_dynamic_table_dynamic_table_dynamic_table_USE_PG_FULLTEXT_SEARCH=true."
                )
            )
