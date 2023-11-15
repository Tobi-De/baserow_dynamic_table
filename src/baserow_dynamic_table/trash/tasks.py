from datetime import timedelta

from baserow_dynamic_table_dynamic_table_dynamic_table.config.celery import app
from django.conf import settings


# noinspection PyUnusedLocal
@app.task(
    bind=True,
)
def mark_old_trash_for_permanent_deletion(self):
    from baserow_dynamic_table_dynamic_table_dynamic_table.core.trash.handler import TrashHandler

    TrashHandler.mark_old_trash_for_permanent_deletion()


# noinspection PyUnusedLocal
@app.task(
    bind=True,
)
def permanently_delete_marked_trash(self):
    from baserow_dynamic_table_dynamic_table_dynamic_table.core.trash.handler import TrashHandler

    TrashHandler.permanently_delete_marked_trash()


# noinspection PyUnusedLocal
@app.on_after_finalize.connect
def setup_period_trash_tasks(sender, **kwargs):
    sender.add_periodic_task(
        timedelta(minutes=settings.OLD_TRASH_CLEANUP_CHECK_INTERVAL_MINUTES),
        mark_old_trash_for_permanent_deletion.s(),
    )
    sender.add_periodic_task(
        timedelta(minutes=settings.OLD_TRASH_CLEANUP_CHECK_INTERVAL_MINUTES),
        permanently_delete_marked_trash.s(),
    )
