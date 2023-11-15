import typing
from typing import NewType

from django.contrib.contenttypes.models import ContentType
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from baserow_dynamic_table.core.mixins import (
    CreatedAndUpdatedOnMixin,
    HierarchicalModelMixin,
    OrderableMixin,
    PolymorphicContentTypeMixin,
    TrashableModelMixin,
)
from baserow_dynamic_table.core.utils import remove_special_characters, to_snake_case
from baserow_dynamic_table.fields.mixins import (
    BaseDateMixin,
)
from baserow_dynamic_table.table.cache import (
    invalidate_table_in_model_cache,
)
from baserow_dynamic_table.table.constants import (
    LINK_ROW_THROUGH_TABLE_PREFIX,
    MULTIPLE_SELECT_THROUGH_TABLE_PREFIX,
    get_tsv_vector_field_name,
)
from .fields import SerialField
from ..mixins import ParentFieldTrashableModelMixin

if typing.TYPE_CHECKING:
    from baserow_dynamic_table.fields.dependencies.handler import (
        FieldDependants,
    )

NUMBER_MAX_DECIMAL_PLACES = 10

NUMBER_DECIMAL_PLACES_CHOICES = [
    (0, "1"),
    (1, "1.0"),
    (2, "1.00"),
    (3, "1.000"),
    (4, "1.0000"),
    (5, "1.00000"),
    (6, "1.000000"),
    (7, "1.0000000"),
    (8, "1.00000000"),
    (9, "1.000000000"),
    (NUMBER_MAX_DECIMAL_PLACES, "1.0000000000"),
]

RATING_STYLE_CHOICES = [
    ("star", "Star"),
    ("heart", "Heart"),
    ("thumbs-up", "Thumbs-up"),
    ("flag", "Flags"),
    ("smile", "Smile"),
]


def get_default_field_content_type():
    return ContentType.objects.get_for_model(Field)


class Field(
    HierarchicalModelMixin,
    TrashableModelMixin,
    CreatedAndUpdatedOnMixin,
    OrderableMixin,
    PolymorphicContentTypeMixin,
    models.Model,
):
    """
    baserow_dynamic_table base field model. All custom fields should inherit from this class.
    Because each field type can have custom settings, for example precision for a number
    field, values for an option field or checkbox style for a boolean field we need a
    polymorphic content type to store these settings in another table.
    """

    table = models.ForeignKey("baserow_dynamic_table.Table", on_delete=models.CASCADE)
    order = models.PositiveIntegerField(help_text="Lowest first.")
    name = models.CharField(max_length=255, db_index=True)
    primary = models.BooleanField(
        default=False,
        help_text="Indicates if the field is a primary field. If `true` the field "
        "cannot be deleted and the value should represent the whole row.",
    )
    content_type = models.ForeignKey(
        ContentType,
        verbose_name="content type",
        related_name="database_fields",
        on_delete=models.SET(get_default_field_content_type),
    )
    field_dependencies = models.ManyToManyField(
        "self",
        related_name="dependant_fields",
        through="FieldDependency",
        through_fields=("dependant", "dependency"),
        symmetrical=False,
    )
    tsvector_column_created = models.BooleanField(
        default=False,
        help_text="Indicates whether a `tsvector` has been created for this field yet. "
        "This value will be False for fields created before the full text "
        "search release which haven't been lazily migrated yet. Or for "
        "users who have turned off full text search entirely.",
    )

    class Meta:
        ordering = (
            "-primary",
            "order",
        )

    def get_parent(self):
        return self.table

    @classmethod
    def get_last_order(cls, table):
        queryset = Field.objects.filter(table=table)
        return cls.get_highest_order_of_queryset(queryset) + 1

    @classmethod
    def get_max_name_length(cls):
        return cls._meta.get_field("name").max_length

    @property
    def db_column(self):
        return f"field_{self.id}"

    @property
    def tsv_db_column(self):
        return get_tsv_vector_field_name(self.id)

    @property
    def tsv_index_name(self):
        return f"tbl_tsv_{self.id}_idx"

    @property
    def model_attribute_name(self):
        """
        Generates a pascal case based model attribute name based on the field name.

        :return: The generated model attribute name.
        :rtype: str
        """

        name = remove_special_characters(self.name, False)
        name = to_snake_case(name)

        if name[0].isnumeric():
            name = f"field_{name}"

        return name

    def invalidate_table_model_cache(self):
        invalidate_table_in_model_cache(self.table_id)

    def dependant_fields_with_types(
        self,
        field_cache=None,
        starting_via_path_to_starting_table=None,
        associated_relation_changed=False,
    ) -> "FieldDependants":
        from baserow_dynamic_table.fields.dependencies.handler import (
            FieldDependencyHandler,
        )

        return FieldDependencyHandler.get_dependant_fields_with_type(
            self.table_id,
            [self.id],
            associated_relation_changed,
            field_cache,
            starting_via_path_to_starting_table,
        )

    def save(self, *args, **kwargs):
        kwargs.pop("field_cache", None)
        kwargs.pop("raise_if_invalid", None)
        save = super().save(*args, **kwargs)
        self.invalidate_table_model_cache()
        return save


class AbstractSelectOption(
    HierarchicalModelMixin, ParentFieldTrashableModelMixin, models.Model
):
    value = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField()
    field = models.ForeignKey(
        Field, on_delete=models.CASCADE, related_name="select_options"
    )

    class Meta:
        abstract = True
        ordering = (
            "order",
            "id",
        )

    def get_parent(self):
        return self.field

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"<SelectOption {self.value} ({self.id})>"


class SelectOption(AbstractSelectOption):
    @classmethod
    def get_max_value_length(cls):
        return cls._meta.get_field("value").max_length


class TextField(Field):
    text_default = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="If set, this value is going to be added every time a new row "
        "created.",
    )


class LongTextField(Field):
    pass


class URLField(Field):
    pass


class NumberField(Field):
    number_decimal_places = models.IntegerField(
        choices=NUMBER_DECIMAL_PLACES_CHOICES,
        default=0,
        help_text="The amount of digits allowed after the point.",
    )
    number_negative = models.BooleanField(
        default=False, help_text="Indicates if negative values are allowed."
    )

    def save(self, *args, **kwargs):
        """Check if the number_decimal_places has a valid choice."""

        if not any(
            self.number_decimal_places in _tuple
            for _tuple in NUMBER_DECIMAL_PLACES_CHOICES
        ):
            raise ValueError(f"{self.number_decimal_places} is not a valid choice.")
        super(NumberField, self).save(*args, **kwargs)


class RatingField(Field):
    max_value = models.PositiveSmallIntegerField(
        default=5,
        help_text="Maximum value the rating can take.",
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    color = models.CharField(
        max_length=50,
        blank=False,
        help_text="Color of the symbols.",
        default="dark-orange",
    )
    style = models.CharField(
        choices=RATING_STYLE_CHOICES,
        default="star",
        max_length=50,
        blank=False,
        help_text=(
            "Rating style. Allowed values: "
            f"{', '.join([value for (value, _) in RATING_STYLE_CHOICES])}."
        ),
    )

    def save(self, *args, **kwargs):
        """
        Check if the max_value, color and style have a valid value.
        """

        if not any(self.style in _tuple for _tuple in RATING_STYLE_CHOICES):
            raise ValueError(f"{self.style} is not a valid choice.")
        if not self.color:
            raise ValueError(f"color should be defined.")

        if self.max_value < 1:
            raise ValueError("Ensure this value is greater than or equal to 1.")
        if self.max_value > 10:
            raise ValueError(f"Ensure this value is less than or equal to 10.")

        super().save(*args, **kwargs)


class BooleanField(Field):
    pass


class DateField(Field, BaseDateMixin):
    pass


class LastModifiedField(Field, BaseDateMixin):
    pass


class CreatedOnField(Field, BaseDateMixin):
    pass


class LinkRowField(Field):
    THROUGH_DATABASE_TABLE_PREFIX = LINK_ROW_THROUGH_TABLE_PREFIX
    link_row_table = models.ForeignKey(
        "baserow_dynamic_table.Table",
        on_delete=models.CASCADE,
        help_text="The table that the field has a relation with.",
        blank=True,
    )
    link_row_related_field = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        help_text="The relation field in the other table.",
        null=True,
        blank=True,
    )
    # link_row_relation_id = SerialField(null=True, unique=False)
    link_row_relation_id = SerialField(unique=False)

    @property
    def through_table_name(self):
        """
        Generating a unique through table name based on the relation id.

        :return: The table name of the through model.
        :rtype: string
        """

        if not self.link_row_relation_id:
            raise ValueError("The link row field does not yet have a relation id.")

        return f"{self.THROUGH_DATABASE_TABLE_PREFIX}{self.link_row_relation_id}"

    def get_related_primary_field(self):
        try:
            return self.link_row_table.field_set.get(primary=True)
        except Field.DoesNotExist:
            return None

    @property
    def is_self_referencing(self):
        return self.link_row_table_id == self.table_id

    @property
    def link_row_table_has_related_field(self):
        return self.link_row_related_field_id is not None


class EmailField(Field):
    pass


class FileField(Field):
    pass


class SingleSelectField(Field):
    pass


class MultipleSelectField(Field):
    THROUGH_DATABASE_TABLE_PREFIX = MULTIPLE_SELECT_THROUGH_TABLE_PREFIX

    @property
    def through_table_name(self):
        """
        Generating a unique through table name based on the relation id.

        :return: The table name of the through model.
        :rtype: string
        """

        return f"{self.THROUGH_DATABASE_TABLE_PREFIX}{self.id}"


class PhoneNumberField(Field):
    pass


class UUIDField(Field):
    pass


SpecificFieldForUpdate = NewType("SpecificFieldForUpdate", Field)
