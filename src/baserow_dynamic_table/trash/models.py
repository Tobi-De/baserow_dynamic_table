from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import UniqueConstraint

from baserow_dynamic_table.table.models import Table

User = get_user_model()


class TrashedRows(models.Model):
    """
    This model keeps track of rows that had been trashed together in batch.
    """

    table = models.ForeignKey(Table, on_delete=models.CASCADE)
    row_ids = models.JSONField()

    @property
    def trashed(self):
        return True


class TrashEntry(models.Model):
    """
    A TrashEntry is a record indicating that another model in Baserow has a trashed
    row. When a user deletes certain things in Baserow they are not actually deleted
    from the database, but instead marked as trashed. Trashed rows can be restored
    or permanently deleted.

    The other model must mixin the TrashableModelMixin and also have a corresponding
    TrashableItemType registered specifying exactly how to delete and restore that
    model.
    """

    # The TrashableItemType.type of the item that is trashed.
    trash_item_type = models.TextField()
    # We need to also store the parent id as for some trashable items the
    # trash_item_type and the trash_item_id is not unique as the items of that type
    # could be spread over multiple tables with the same id.
    parent_trash_item_id = models.PositiveIntegerField(null=True, blank=True)
    # The actual id of the item that is trashed
    trash_item_id = models.PositiveIntegerField()

    trash_item_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="private_trash_entries",
    )

    # If the user who trashed something gets deleted we still wish to preserve this
    # trash record as it is independent of if the user exists or not.
    user_who_trashed = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    # The workspace and application fields are used to workspace trash into
    # separate "bins" which can be viewed and emptied independently of each other.

    # The application the item that is trashed is found in, if the trashed item is the
    # application itself then this should also be set to that trashed application.
    # application = models.ForeignKey(
    #     Application, on_delete=models.CASCADE, null=True, blank=True
    # )

    # When set to true this trash entry will be picked up by a periodic job and the
    # underlying item will be actually permanently deleted along with the entry.
    should_be_permanently_deleted = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(auto_now_add=True)

    # The name, name of the parent and any extra description are cached so lookups
    # of trashed items are simple and do not require joining to many different tables
    # to simply get these details.
    name = models.TextField()
    # If multiple items have been deleted via one trash entry, for example with a
    # batch update, the names can be provided here. The client can then visualize
    # this differently.
    names = ArrayField(base_field=models.TextField(), null=True)
    parent_name = models.TextField(null=True, blank=True)
    extra_description = models.TextField(null=True, blank=True)

    # this permits to trash items together with a single entry
    related_items = models.JSONField(default=dict, null=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["trash_item_type", "parent_trash_item_id", "trash_item_id"],
                name="unique_with_parent_trash_item_id",
            ),
            UniqueConstraint(
                fields=["trash_item_type", "trash_item_id"],
                condition=models.Q(parent_trash_item_id=None),
                name="unique_without_parent_trash_item_id",
            ),
        ]
        indexes = [models.Index(fields=["-trashed_at", "trash_item_type"])]
