from collections import defaultdict

from django.conf import settings
from django.db import transaction

from loguru import logger

from baserow.config.celery import app
from baserow_dynamic_table.table.object_scopes import DatabaseTableObjectScopeType
from baserow_dynamic_table.table.operations import (
    ListenToAllDatabaseTableEventsOperationType,
)
from baserow_dynamic_table.ws.pages import TablePageType
from baserow.core.exceptions import PermissionException
from baserow.core.handler import CoreHandler
from baserow.core.mixins import TrashableModelMixin
from baserow.core.models import Workspace
from baserow.core.object_scopes import WorkspaceObjectScopeType
from baserow.core.registries import (
    PermissionManagerType,
    object_scope_type_registry,
    subject_type_registry,
)
from baserow.core.subjects import UserSubjectType
from baserow.ws.tasks import send_message_to_channel_group


@app.task(queue="export")
def run_row_count_job():
    """
    Runs the row count job to keep track of how many rows
    are being used by each table.
    """

    from baserow_dynamic_table.table.handler import TableHandler

    if CoreHandler().get_settings().track_workspace_usage:
        TableHandler.count_rows()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.BASEROW_ROW_COUNT_JOB_CRONTAB,
        run_row_count_job.s(),
    )


def unsubscribe_subject_from_tables_currently_subscribed_to(
    subject_id: int,
    subject_type_name: str,
    scope_id: int,
    scope_type_name: str,
    workspace_id: int,
    permission_manager: PermissionManagerType = None,
):
    """
    Unsubscribes all users associated to a subject from the tables they are currently
    subscribed to. Optionally you can also recheck their permissions before deciding
    to unsubscribe them.

    :param subject_id: The id for the subject we are trying to unsubscribe
    :param subject_type_name: The name of the subject type
    :param scope_id: The id of the scope the subject should be removed from
    :param scope_type_name: The name of the scope type
    :param workspace_id: The id of the workspace in which context this is executed
    :param permission_manager: Optional parameter used to check permissions
    """

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    workspace = Workspace.objects.get(pk=workspace_id)

    subject_type = subject_type_registry.get(subject_type_name)
    scope_type = object_scope_type_registry.get(scope_type_name)

    if issubclass(subject_type.model_class, TrashableModelMixin):
        subject_type_qs = subject_type.model_class.objects_and_trash
    else:
        subject_type_qs = subject_type.model_class.objects

    subject = subject_type_qs.get(pk=subject_id)
    scope = scope_type.model_class.objects.get(pk=scope_id)

    users = subject_type.get_users_included_in_subject(subject)
    tables = DatabaseTableObjectScopeType().get_all_context_objects_in_scope(scope)

    channel_group_names_users_dict = defaultdict(set)
    for user in users:
        for table in tables:
            channel_group_name = TablePageType().get_permission_channel_group_name(
                table.id
            )
            if permission_manager is None:
                channel_group_names_users_dict[channel_group_name].add(user.id)
            else:
                try:
                    permission_manager.check_permissions(
                        user,
                        ListenToAllDatabaseTableEventsOperationType.type,
                        workspace=workspace,
                        context=table,
                    )
                except PermissionException:
                    channel_group_names_users_dict[channel_group_name].add(user.id)

    channel_layer = get_channel_layer()

    for channel_group_name, user_ids in channel_group_names_users_dict.items():
        async_to_sync(send_message_to_channel_group)(
            channel_layer,
            channel_group_name,
            {
                "type": "users_removed_from_permission_group",
                "user_ids_to_remove": list(user_ids),
                "permission_group_name": channel_group_name,
            },
        )


@app.task(bind=True)
def unsubscribe_user_from_tables_when_removed_from_workspace(
    self,
    user_id: int,
    workspace_id: int,
):
    """
    Task that will unsubscribe the provided user from web socket
    CoreConsumer pages that belong to the provided workspace.

    :param user_id: The id of the user that is supposed to be unsubscribed.
    :param workspace_id: The id of the workspace the user belonged to.
    """

    unsubscribe_subject_from_tables_currently_subscribed_to(
        user_id,
        UserSubjectType.type,
        workspace_id,
        WorkspaceObjectScopeType.type,
        workspace_id,
    )


@app.task(
    bind=True,
    queue="export",
)
def setup_new_background_update_and_search_columns(self, table_id: int):
    """ """

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
        SearchHandler.update_tsvector_columns(
            table, update_tsvectors_for_changed_rows_only=False
        )
    except PostgresFullTextSearchDisabledException:
        logger.debug(f"Postgres full-text search is disabled.")
