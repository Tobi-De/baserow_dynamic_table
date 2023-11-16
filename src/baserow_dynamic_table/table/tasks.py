from django.conf import settings
from django.db import transaction
from loguru import logger


@app.task(queue="export")
def run_row_count_job():
    """
    Runs the row count job to keep track of how many rows
    are being used by each table.
    """

    from baserow_dynamic_table.table.handler import TableHandler

    # TODO: settings to enable or disable this
    TableHandler.count_rows()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.baserow_dynamic_table_ROW_COUNT_JOB_CRONTAB,
        run_row_count_job.s(),
    )


@app.task(
    bind=True,
    queue="export",
)
def setup_new_background_update_and_search_columns(self, table_id: int):
    """
    Responsible for migrating baserow tables into using our new Postgres
    full-text search functionality. When a view is loaded, the receiver
    `view_loaded_maybe_create_tsvector` will detect if it's ready for
    migrating, and if it passes some checks, this Celery task is enqueued.

    Our job in this task is to:
        1. Select the table FOR UPDATE.
        2. Create the new `needs_background_update` column and index.
        3. Create tsvector columns and indices for all searchable fields.
        4. Update those tsvector columns so that they can be searched.
    """

    from baserow_dynamic_table.search.exceptions import (
        PostgresFullTextSearchDisabledException,
    )
    from baserow_dynamic_table.search.handler import SearchHandler
    from baserow_dynamic_table.table.handler import TableHandler

    with transaction.atomic():
        table = TableHandler().get_table_for_update(table_id)
        TableHandler().create_needs_background_update_field(table)

        try:
            SearchHandler.sync_tsvector_columns(table)
        except PostgresFullTextSearchDisabledException:
            logger.debug(f"Postgres full-text search is disabled.")

    try:
        # The `update_tsvectors_for_changed_rows_only` is set to `True` here because
        # it's okay to keep looping over the rows until all tsv columns are updated.
        # This will also prevent deadlocks if any of the rows are updated, because the
        # `update_tsvector_columns` acquires a lock while it's running.
        SearchHandler.update_tsvector_columns_locked(
            table, update_tsvectors_for_changed_rows_only=True
        )
    except PostgresFullTextSearchDisabledException:
        logger.debug(f"Postgres full-text search is disabled.")
