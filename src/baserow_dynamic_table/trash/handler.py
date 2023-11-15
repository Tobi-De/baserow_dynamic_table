from typing import Any, Dict, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from loguru import logger

from baserow_dynamic_table.core.exceptions import (
    TrashItemDoesNotExist,
    is_max_lock_exceeded_exception,
)
from baserow_dynamic_table.trash.exceptions import (
    CannotDeleteAlreadyDeletedItem,
    CannotRestoreChildBeforeParent,
    CannotRestoreItemNotOwnedByUser,
    ParentIdMustBeProvidedException,
    ParentIdMustNotBeProvidedException,
    PermanentDeletionMaxLocksExceededException,
)
from baserow_dynamic_table.trash.models import TrashEntry
from baserow_dynamic_table.trash.registries import (
    TrashableItemType,
    trash_item_type_registry,
)

User = get_user_model()


class TrashHandler:
    @staticmethod
    def trash(
        requesting_user: User,
        trash_item,
        existing_trash_entry: Optional[TrashEntry] = None,
    ) -> TrashEntry:
        """
        Marks the provided trashable item as trashed meaning it will no longer be
        visible or usable in baserow_dynamic_table. However, any user with access to its workspace can
        restore the item after it is trashed to make it visible and usable again. After
        a configurable timeout period or when the user explicitly empties the
        trash trashed items will be permanently deleted.

        :param requesting_user: The user who is requesting that this item be trashed.
        :param workspace: The workspace the trashed item is in.
        :param application: If the item is in an application the application.
        :param trash_item: The item to be trashed.
        :param existing_trash_entry: An optional TrashEntry that the handler can
            pass to the trash system to track cascading deletions in a single
            trash entry.
        :return: A newly created entry in the TrashEntry table for this item.
        """

        # Check if the parent has a trash entry, if so link this new entry to it
        # via a cascading on delete FK to ensure if the parent entry is deleted then
        # this one is also deleted. We do this as say if a table is perm deleted,
        # we don't then want to
        with transaction.atomic():
            trash_item_type = trash_item_type_registry.get_by_model(trash_item)

            if existing_trash_entry is None:
                parent = trash_item_type.get_parent(trash_item)
                if parent is None:
                    parent_name = None
                    parent_trash_item_id = None
                else:
                    parent_type = trash_item_type_registry.get_by_model(parent)
                    parent_name = parent_type.get_name(parent)
                    parent_trash_item_id = (
                        parent.id if trash_item_type.requires_parent_id else None
                    )
                _check_parent_id_valid(parent_trash_item_id, trash_item_type)
                try:
                    trash_entry = TrashEntry.objects.create(
                        user_who_trashed=requesting_user,
                        trash_item_type=trash_item_type.type,
                        trash_item_id=trash_item.id,
                        name=trash_item_type.get_name(trash_item),
                        names=trash_item_type.get_names(trash_item),
                        parent_name=parent_name,
                        parent_trash_item_id=parent_trash_item_id,
                        trash_item_owner=trash_item_type.get_owner(trash_item),
                    )
                except IntegrityError as e:
                    if "unique constraint" in e.args[0]:
                        raise CannotDeleteAlreadyDeletedItem()
                    else:
                        raise e
            else:
                trash_entry = existing_trash_entry

            trash_item_type.trash(trash_item, requesting_user, trash_entry)

            return trash_entry

    @classmethod
    def get_trash_entry(cls, trash_item_type, trash_item_id, parent_trash_item_id=None):
        trashable_item_type = trash_item_type_registry.get(trash_item_type)
        _check_parent_id_valid(parent_trash_item_id, trashable_item_type)

        if hasattr(trashable_item_type, "deprecated_in_favor_of"):
            trash_item_type = trashable_item_type.deprecated_in_favor_of

        return _get_trash_entry(trash_item_type, parent_trash_item_id, trash_item_id)

    @classmethod
    def restore_item(
        cls, user, trash_item_type, trash_item_id, parent_trash_item_id=None
    ):
        """
        Restores an item from the trash re-instating it back in baserow_dynamic_table exactly how it
        was before it was trashed.
        :param user: The user requesting to restore trashed item.
        :param trash_item_type: The trashable item type of the item to restore.
        :param parent_trash_item_id: The parent id of the item to restore.
        :param trash_item_id: The trash item id of the item to restore.
        :raises CannotRestoreChildBeforeParent: Raised if the item being restored has
            any parent, or parent of a parent etc which is trashed as that item should
            be restored first.
        """

        with transaction.atomic():
            trash_entry = cls.get_trash_entry(
                trash_item_type, trash_item_id, parent_trash_item_id
            )
            trashable_item_type = trash_item_type_registry.get(trash_item_type)
            trash_item = trashable_item_type.lookup_trashed_item(trash_entry, {})

            if TrashHandler.item_has_a_trashed_parent(
                trash_item,
            ):
                raise CannotRestoreChildBeforeParent()

            if (
                trash_entry.trash_item_owner is not None
                and trash_entry.trash_item_owner != user
            ):
                raise CannotRestoreItemNotOwnedByUser()

            trash_entry.delete()

            restore_type = trash_item_type_registry.get_by_model(trash_item)
            restore_type.restore(trash_item, trash_entry)

    @staticmethod
    def mark_old_trash_for_permanent_deletion():
        """
        Updates all trash entries which are older than a django setting for permanent
        deletion. Does not perform the deletion itself.
        """

        now = timezone.now()
        hours = settings.HOURS_UNTIL_TRASH_PERMANENTLY_DELETED
        cutoff = now - timezone.timedelta(hours=hours)
        updated_count = TrashEntry.objects.filter(trashed_at__lte=cutoff).update(
            should_be_permanently_deleted=True
        )
        logger.info(
            f"Successfully marked {updated_count} old trash items for deletion as they "
            f"were older than {hours} hours."
        )

    @staticmethod
    def empty(requesting_user: User, workspace_id: int, application_id: Optional[int]):
        """
        Marks all items in the selected workspace (or application in the workspace if
        application_id is provided) as should be permanently deleted.
        """

        with transaction.atomic():
            trash_contents = TrashHandler.get_trash_contents_for_emptying(
                requesting_user, workspace_id, application_id
            )
            trash_contents.update(should_be_permanently_deleted=True)

    @staticmethod
    def try_perm_delete_trash_entry(
        trash_entry: TrashEntry,
        trash_item_lookup_cache: Optional[Dict[str, Any]] = None,
    ):
        """
        Responsible for finding the trash item type for this `TrashEntry`, then finding
        the model to destroy and passing it into `_permanently_delete_and_signal`
        for it to be permanently deleted.
        """ ""

        trash_item_type = trash_item_type_registry.get(trash_entry.trash_item_type)

        try:
            to_delete = trash_item_type.lookup_trashed_item(
                trash_entry, trash_item_lookup_cache
            )
            TrashHandler._permanently_delete_and_signal(
                trash_item_type,
                to_delete,
                trash_entry.parent_trash_item_id,
                trash_item_lookup_cache,
            )
        except TrashItemDoesNotExist:
            # When a parent item is deleted it should also delete all of its
            # children. Hence we expect that many of these TrashEntries to no
            # longer point to an existing item. In such a situation we just want
            # to delete the entry as the item itself has been correctly deleted.
            pass
        except OperationalError as e:
            # Detect if this `OperationalError` is due to us exceeding the
            # lock count in `max_locks_per_transaction`. If it is, we'll
            # raise a different exception so that we can catch this scenario.
            if is_max_lock_exceeded_exception(e):
                raise PermanentDeletionMaxLocksExceededException()
            raise e

    @staticmethod
    def permanently_delete_marked_trash():
        """
        Looks up every trash item marked for permanent deletion and removes them
        irreversibly from the database along with their corresponding trash entries.
        """

        trash_item_lookup_cache = {}
        deleted_count = 0
        while True:
            with transaction.atomic():
                # Perm deleting a workspace or application can cause cascading deletion
                # of other trash entries hence we only look up one a time. If we instead
                # looped over a single queryset lookup of all TrashEntries then we could
                # end up trying to delete TrashEntries which have already been deleted
                # by a previous cascading delete of a workspace or application.
                trash_entry = TrashEntry.objects.filter(
                    should_be_permanently_deleted=True
                ).first()
                if not trash_entry:
                    break

                TrashHandler.try_perm_delete_trash_entry(
                    trash_entry, trash_item_lookup_cache
                )
                trash_entry.delete()
                deleted_count += 1
        logger.info(
            f"Successfully deleted {deleted_count} trash entries and their associated "
            "trashed items."
        )

    @staticmethod
    def _permanently_delete_and_signal(
        trash_item_type: Any,
        to_delete: Any,
        parent_id: Optional[int],
        trash_item_lookup_cache: Optional[Dict[str, Any]] = None,
    ):
        """
        Internal method which actually permanently deletes the provided to_delete object
        and also triggers the correct signal so plugins can do appropriate clean-up.

        :param trash_item_type: The trashable item type of the item being deleted.
        :param to_delete: The actual instance of the thing to delete.
        :param parent_id: If required for the trashable item type then the id of the
            parent of to_delete.
        :param trash_item_lookup_cache: An optional dictionary used for caching during
            many different invocations of permanently_delete.
        """

        _check_parent_id_valid(parent_id, trash_item_type)
        trash_item_id = to_delete.id
        trash_item_type.permanently_delete_item(
            to_delete,
            trash_item_lookup_cache,
        )

    @staticmethod
    def permanently_delete(trashable_item, parent_id=None):
        """
        Actually removes the provided trashable item from the database irreversibly.
        :param trashable_item: An instance of a TrashableItemType model_class to delete.
        :param parent_id: If required to look-up the item to delete or related items
            this should be set to the parent id of the item to delete.
        """

        trash_item_type = trash_item_type_registry.get_by_model(trashable_item)
        TrashHandler._permanently_delete_and_signal(
            trash_item_type, trashable_item, parent_id
        )

    @staticmethod
    def get_trash_contents_for_emptying(
        user: User, workspace_id: int, application_id: Optional[int]
    ) -> QuerySet:
        """
        Looks up the trash contents for a particular workspace optionally filtered by
        the provided application id.
        :param user: The user who is requesting to see the trash contents.
        :param workspace_id: The workspace to lookup trash contents inside of.
        :param application_id: The optional application to filter down the trash
            contents to only this workspace.
        :raises WorkspaceDoesNotExist: If the workspace_id is for an non
            existent workspace.
        :raises ApplicationDoesNotExist: If the application_id is for an non
            existent application.
        :raises ApplicationNotInWorkspace: If the application_id is for an application
            not in the requested workspace.
        :raises UserNotInWorkspace: If the user does not belong to the workspace.
        :return: a queryset of the trash items in the workspace optionally filtered by
            the provided application.
        """

        trash_contents = TrashEntry.objects.filter(should_be_permanently_deleted=False)

        return trash_contents

    @staticmethod
    def get_trash_contents(
        user: User, workspace_id: int, application_id: Optional[int]
    ) -> QuerySet:
        """
        Looks up the trash contents for a particular workspace optionally filtered by
        the provided application id.
        :param user: The user who is requesting to see the trash contents.
        :param workspace_id: The workspace to lookup trash contents inside of.
        :param application_id: The optional application to filter down the trash
            contents to only this workspace.
        :raises WorkspaceDoesNotExist: If the workspace_id is for an non
            existent workspace.
        :raises ApplicationDoesNotExist: If the application_id is for an non
            existent application.
        :raises ApplicationNotInWorkspace: If the application_id is for an application
            not in the requested workspace.
        :raises UserNotInWorkspace: If the user does not belong to the workspace.
        :return: a queryset of the trash items in the workspace optionally filtered by
            the provided application.
        """

        trash_contents = TrashEntry.objects.filter(
            should_be_permanently_deleted=False
        ).filter(Q(trash_item_owner=user) | Q(trash_item_owner__isnull=True))

        return trash_contents.order_by("-trashed_at")

    @staticmethod
    def item_has_a_trashed_parent(item, check_item_also=False):
        """
        Given an instance of a model which is trashable (item) checks if it has a parent
        which is trashed. Returns True if it's parent, or parent's parent (and so on)
        is trashed, False if no parent is trashed.

        :param check_item_also: If true also checks if the provided item itself is
            trashed and returns True if so.
        :param item: An instance of a trashable model to check.
        :return: If the provided item has a trashed parent or not.
        """

        trash_item_type = trash_item_type_registry.get_by_model(item)

        if check_item_also and item.trashed:
            return True

        while True:
            parent = trash_item_type.get_parent(item)
            if parent is None:
                return False
            elif parent.trashed:
                return True
            else:
                item = parent
                trash_item_type = trash_item_type_registry.get_by_model(item)


def _check_parent_id_valid(
    parent_trash_item_id: Optional[int], trashable_item_type: TrashableItemType
):
    """
    Raises an exception if the parent id is missing when it is required, or when the
    parent id is included when it is not required.

    Because the parent id is stored in the database and used to lookup trash entries
    uniquely, we want to enforce it is not provided when not needed. For example, if
    the API allowed you to provide a parent id when trashing a table, that id will then
    be stored, and it must then be provided when trying to restore that table otherwise
    the entry will not be found. Hence by being strict we ensure it's not possible to
    accidentally trash an item which is hard to then restore.

    :param parent_trash_item_id: The parent id
    :param trashable_item_type: The type to check to see if it needs a parent id or not.
    :return:
    """

    if trashable_item_type.requires_parent_id and parent_trash_item_id is None:
        raise ParentIdMustBeProvidedException()
    if not trashable_item_type.requires_parent_id and parent_trash_item_id is not None:
        raise ParentIdMustNotBeProvidedException()


def _get_trash_entry(
    trash_item_type: str,
    parent_trash_item_id: Optional[int],
    trash_item_id: int,
) -> TrashEntry:
    """
    Gets the trash entry for a particular resource in baserow_dynamic_table which has been
    trashed.
    :param trash_item_id: The id of the item to look for a trash entry for.
    :param parent_trash_item_id: The parent id of the item to look for a trash
        entry for.
    :param trash_item_type: The trashable type of the item.
    :returns The trash entry for the specified baserow_dynamic_table item.
    :raises UserNotInWorkspace: If the requesting_user is not in the trashed items
        workspace.
    """

    try:
        trash_entry = TrashEntry.objects.get(
            parent_trash_item_id=parent_trash_item_id,
            trash_item_id=trash_item_id,
            trash_item_type=trash_item_type,
        )
    except TrashEntry.DoesNotExist:
        raise TrashItemDoesNotExist()
    return trash_entry
