from django.db import models
from django.db.models.expressions import RawSQL
from django.db.models.fields.related_descriptors import (
    ForwardManyToOneDescriptor,
    ManyToManyDescriptor,
)
from django.utils.functional import cached_property

from baserow_dynamic_table.core.fields import SyncedDateTimeField


class BaserowLastModifiedField(SyncedDateTimeField):
    requires_refresh_after_update = True


class SingleSelectForwardManyToOneDescriptor(ForwardManyToOneDescriptor):
    def get_queryset(self, **hints):
        """
        We specifically want to return a new query set without the provided hints
        because the related table could be in another database and that could fail
        otherwise.
        """

        return self.field.remote_field.model.objects.all()

    def get_object(self, instance):
        """
        Tries to fetch the reference object, but if it fails because it doesn't exist,
        the value will be set to None instead of failing hard.
        """

        try:
            return super().get_object(instance)
        except self.field.remote_field.model.DoesNotExist:
            setattr(instance, self.field.name, None)
            instance.save()
            return None


class SingleSelectForeignKey(models.ForeignKey):
    forward_related_accessor_class = SingleSelectForwardManyToOneDescriptor


class MultipleSelectManyToManyDescriptor(ManyToManyDescriptor):
    """
    This is a slight modification of Djangos default ManyToManyDescriptor for the
    MultipleSelectFieldType. This is needed in order to change the default ordering of
    the select_options that are being returned when accessing those by calling ".all()"
    on the field. The default behavior was that no ordering is applied, which in the
    case for the MultipleSelectFieldType meant that the relations were ordered by
    their ID. To show the relations in the order of how the user added those to
    the field, the `get_queryset` and `get_prefetch_queryset` method was modified by
    applying an order_by. The `order_by` is using the id of the through table.

    Optionally it's also possible to provide a `additional_filters` dict parameter.
    It can contain additional filters that must be applied to the queryset.

    The changes are compatible for a normal and prefetched queryset.
    """

    def __init__(self, *args: list, **kwargs: dict):
        """
        :param additional_filters: Can contain additional filters that must be
            applied to the queryset. For example `{"id__in": [1, 2]}` makes sure that
            only results where the id is either `1` or `2` is returned.
        """

        self.additional_filters = kwargs.pop("additional_filters", None)
        super().__init__(*args, **kwargs)

    @cached_property
    def related_manager_cls(self):
        additional_filters = self.additional_filters
        manager_class = super().related_manager_cls

        class CustomManager(manager_class):
            def __init__(self, instance=None):
                super().__init__(instance=instance)
                self.additional_filters = additional_filters

                if self.additional_filters:
                    self.core_filters.update(**additional_filters)

            def _apply_rel_ordering(self, queryset):
                return queryset.extra(order_by=[f"{self.through._meta.db_table}.id"])

            def get_queryset(self):
                try:
                    return self.instance._prefetched_objects_cache[
                        self.prefetch_cache_name
                    ]
                except (AttributeError, KeyError):
                    queryset = super().get_queryset()
                    queryset = self._apply_rel_ordering(queryset)
                    return queryset

            def get_prefetch_queryset(self, instances, queryset=None):
                returned_tuple = list(
                    super().get_prefetch_queryset(instances, queryset)
                )

                if self.additional_filters:
                    returned_tuple[0] = returned_tuple[0].filter(**additional_filters)

                returned_tuple[0] = returned_tuple[0].extra(
                    order_by=[f"{self.through._meta.db_table}.id"]
                )

                return tuple(returned_tuple)

        return CustomManager


class MultipleSelectManyToManyField(models.ManyToManyField):
    """
    This is a slight modification of Djangos default ManyToManyField to apply the
    custom `MultipleSelectManyToManyDescriptor` to the class of the model.
    """

    def __init__(self, *args, **kwargs):
        self.additional_filters = kwargs.pop("additional_filters", None)
        self.reversed_additional_filters = kwargs.pop(
            "reversed_additional_filters", None
        )
        super().__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)
        setattr(
            cls,
            self.name,
            MultipleSelectManyToManyDescriptor(
                self.remote_field,
                reverse=False,
                additional_filters=self.additional_filters,
            ),
        )

    def contribute_to_related_class(self, cls, related):
        super().contribute_to_related_class(cls, related)
        if (
                not self.remote_field.is_hidden()
                and not related.related_model._meta.swapped
        ):
            setattr(
                cls,
                related.get_accessor_name(),
                MultipleSelectManyToManyDescriptor(
                    self.remote_field,
                    reverse=True,
                    additional_filters=self.reversed_additional_filters,
                ),
            )


class SerialField(models.Field):
    """
    The serial field works very similar compared to the `AutoField` (primary key field).
    Everytime a new row is created and the value is not set, it will automatically
    increment a sequence and that will be set as value. It's basically an auto
    increment column. The sequence is independent of a transaction to prevent race
    conditions.
    """

    db_returning = True

    def db_type(self, connection):
        return "serial"

    def pre_save(self, model_instance, add):
        if add and not getattr(model_instance, self.name):
            sequence_name = f"{model_instance._meta.db_table}_{self.name}_seq"
            return RawSQL(  # nosec
                f"nextval('{sequence_name}'::regclass)",
                (),
            )
        else:
            return super().pre_save(model_instance, add)


class DurationFieldUsingPostgresFormatting(models.DurationField):
    def to_python(self, value):
        return value

    def select_format(self, compiler, sql, params):
        # We want to use postgres's method of converting intervals to strings instead
        # of pythons timedelta representation. This is so lookups of date intervals
        # which cast the interval to string inside of the database will have the
        # same values as non lookup intervals. The postgres str representation is also
        # more human readable.
        return sql + "::text", params
