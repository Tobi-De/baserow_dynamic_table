from django.core.management import BaseCommand

from baserow_dynamic_table.table.cache import clear_generated_model_cache


class Command(BaseCommand):
    help = "Clears baserow's internal generated model cache"

    def handle(self, *args, **options):
        clear_generated_model_cache()
