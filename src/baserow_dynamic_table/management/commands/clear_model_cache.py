from baserow_dynamic_table.table.cache import clear_generated_model_cache
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Clears baserow_dynamic_table_dynamic_table_dynamic_table's internal generated model cache"

    def handle(self, *args, **options):
        clear_generated_model_cache()
