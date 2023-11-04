import typing
from functools import lru_cache
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    ValuesView,
)

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from rest_framework import serializers
from rest_framework.serializers import Serializer

from baserow_dynamic_table.fields.exceptions import InstanceTypeDoesNotExist, InstanceTypeAlreadyRegistered

if typing.TYPE_CHECKING:
    from django.contrib.contenttypes.models import ContentType


class Instance(object):
    """
    This abstract class represents a custom instance that can be added to the registry.
    It must be extended so properties and methods can be added.
    """

    type: str
    """A unique string that identifies the instance."""

    compat_type: str = ""
    """ If this instance has been renamed, and we want to support
        compatibility of the original `type`, implement it with `compat_type`. """

    def __init__(self):
        if not self.type:
            raise ImproperlyConfigured("The type of an instance must be set.")


DjangoModel = TypeVar("DjangoModel", bound=models.Model)


class ModelInstanceMixin(Generic[DjangoModel]):
    """
    This mixin introduces a model_class that will be related to the instance. It is to
    be used in combination with a registry that extends the ModelRegistryMixin.
    """

    model_class: Type[DjangoModel]

    def __init__(self):
        if not self.model_class:
            raise ImproperlyConfigured("The model_class of an instance must be set.")

    def get_content_type(self) -> "ContentType":
        """
        Returns the content_type related to the model_class.
        """

        from django.contrib.contenttypes.models import ContentType

        return ContentType.objects.get_for_model(self.model_class)

    def get_object_for_this_type(self, **kwargs) -> DjangoModel:
        """
        Returns the object given the filters in parameter.
        """

        return self.get_content_type().get_object_for_this_type(**kwargs)

    def get_all_objects_for_this_type(self, **kwargs) -> models.QuerySet[DjangoModel]:
        """
        Returns a queryset to get the objects given the filters in parameter.
        """

        return self.get_content_type().get_all_objects_for_this_type(**kwargs)


class CustomFieldsInstanceMixin:
    """
    If an instance can have custom fields per type, they can be defined here.
    """

    allowed_fields = []
    """The field names that are allowed to set when creating and updating"""

    serializer_field_names = []
    """The field names that must be added to the serializer."""

    request_serializer_field_names = None
    """
    The field names that must be added to the request serializer if different from
    the `serializer_field_names`.
    """

    serializer_field_overrides = {}
    """The fields that must be added to the serializer."""

    request_serializer_field_overrides = None
    """
    The fields that must be added to the request serializer if different from the
    `serializer_field_overrides` property.
    """

    serializer_mixins = []
    """
    The serializer mixins that must be added to the serializer. This property is
    useful if you want to add some custom SerializerMethodField for example.
    """

    serializer_extra_kwargs = None
    """
    The extra kwargs that must be added to the serializer fields. This property is
    useful if you want to add some custom `write_only` field for example.
    """

    def __init__(self):
        """
        :raises ValueError: If the object does not have a `model_class` attribute.
        """

        model_class = getattr(self, "model_class")
        if not model_class:
            raise ValueError(
                "Attribute model_class must be set, maybe you forgot to "
                "extend the ModelInstanceMixin?"
            )

 

T = TypeVar("T")

InstanceSubClass = TypeVar("InstanceSubClass", bound=Instance)


class Registry(Generic[InstanceSubClass]):
    name: str
    """The unique name that is used when raising exceptions."""

    does_not_exist_exception_class = InstanceTypeDoesNotExist
    """The exception that is raised when an instance doesn't exist."""

    already_registered_exception_class = InstanceTypeAlreadyRegistered
    """The exception that is raised when an instance is already registered."""

    def __init__(self):
        if not getattr(self, "name", None):
            raise ImproperlyConfigured(
                "The name must be set on an "
                "InstanceModelRegistry to raise proper errors."
            )

        self.registry: Dict[str, InstanceSubClass] = {}

    def get(self, type_name: str) -> InstanceSubClass:
        """
        Returns a registered instance of the given type name.

        :param type_name: The unique name of the registered instance.
        :type type_name: str
        :raises InstanceTypeDoesNotExist: If the instance with the provided `type_name`
            does not exist in the registry.
        :return: The requested instance.
        :rtype: InstanceModelInstance
        """

        # If the `type_name` isn't in the registry, we may raise DoesNotExist.
        if type_name not in self.registry:
            if type_name_via_compat := self.get_by_type_name_by_compat(type_name):
                type_name = type_name_via_compat
            else:
                raise self.does_not_exist_exception_class(
                    type_name, f"The {self.name} type {type_name} does not exist."
                )

        return self.registry[type_name]

    def get_by_type_name_by_compat(self, compat_name: str) -> Optional[str]:
        """
        Returns a registered instance's `type` by using the compatibility name.
        """

        for instance in self.get_all():
            if instance.compat_type == compat_name:
                return instance.type

    def get_by_type(self, instance_type: Type[InstanceSubClass]) -> InstanceSubClass:
        return self.get(instance_type.type)

    def get_all(self) -> ValuesView[InstanceSubClass]:
        """
        Returns all registered instances

        :return: A list of the registered instances.
        :rtype: List[InstanceModelInstance]
        """

        return self.registry.values()

    def get_types(self) -> List[str]:
        """
        Returns a list of available type names.

        :return: The list of available types.
        :rtype: List
        """

        return list(self.registry.keys())

    def get_types_as_tuples(self) -> List[Tuple[str, str]]:
        """
        Returns a list of available type names.

        :return: The list of available types.
        :rtype: List[Tuple[str,str]]
        """

        return [(k, k) for k in self.registry.keys()]

    def register(self, instance: InstanceSubClass):
        """
        Registers a new instance in the registry.

        :param instance: The instance that needs to be registered.
        :type instance: Instance
        :raises ValueError: When the provided instance is not an instance of Instance.
        :raises InstanceTypeAlreadyRegistered: When the instance's type has already
            been registered.
        """

        if not isinstance(instance, Instance):
            raise ValueError(f"The {self.name} must be an instance of " f"Instance.")

        if instance.type in self.registry:
            raise self.already_registered_exception_class(
                f"The {self.name} with type {instance.type} is already registered."
            )

        self.registry[instance.type] = instance

    def unregister(self, value: InstanceSubClass):
        """
        Removes a registered instance from the registry. An instance or type name can be
        provided as value.

        :param value: The instance or type name.
        :type value: Instance or str
        :raises ValueError: If the provided value is not an instance of Instance or
            string containing the type name.
        """

        if isinstance(value, Instance):
            for type_name, instance in self.registry.items():
                if instance == value:
                    value = type_name

        if isinstance(value, str):
            del self.registry[value]
        else:
            raise ValueError(
                f"The value must either be an {self.name} instance or " f"type name"
            )


class ModelRegistryMixin(Generic[DjangoModel, InstanceSubClass]):
    def get_by_model(
            self, model_instance: Union[DjangoModel, Type[DjangoModel]]
    ) -> InstanceSubClass:
        """
        Returns a registered instance of the given model class.

        :param model_instance: The value that must be a Model class or
            an instance of any model_class.
        :raises InstanceTypeDoesNotExist: When the provided model instance is not
            found in the registry.
        :return: The registered instance.
        """

        if isinstance(model_instance, type):
            clazz = model_instance
        else:
            clazz = type(model_instance)

        return self.get_for_class(clazz)

    @lru_cache
    def get_for_class(self, clazz: Type[DjangoModel]) -> InstanceSubClass:
        """
        Returns a registered instance of the given model class.

        :param model_instance: The value that must be a Model class.
        :raises InstanceTypeDoesNotExist: When the provided model instance is not
            found in the registry.
        :return: The registered instance.
        """

        most_specific_value = None
        for value in self.registry.values():
            value_model_class = value.model_class
            if value_model_class == clazz or issubclass(clazz, value_model_class):
                if most_specific_value is None:
                    most_specific_value = value
                else:
                    # There might be values where one is a sub type of another. The
                    # one with the longer mro is the more specific type (it inherits
                    # from more base classes)
                    most_specific_num_base_classes = len(
                        most_specific_value.model_class.mro()
                    )
                    value_num_base_classes = len(value_model_class.mro())
                    if value_num_base_classes > most_specific_num_base_classes:
                        most_specific_value = value

        if most_specific_value is not None:
            return most_specific_value

        raise self.does_not_exist_exception_class(
            f"The {self.name} model {clazz} does not exist."
        )

    def get_all_by_model_isinstance(
            self, model_instance: DjangoModel
    ) -> List[InstanceSubClass]:
        """
        Returns all registered types which are an instance of the provided
        model_instance.
        """

        all_matching_non_abstract_types = []
        for value in self.registry.values():
            value_model_class = value.model_class
            if value_model_class == model_instance or isinstance(
                    model_instance, value_model_class
            ):
                all_matching_non_abstract_types.append(value)

        return all_matching_non_abstract_types


class CustomFieldsRegistryMixin(Generic[DjangoModel]):
    def get_serializer(
            self,
            model_instance_or_instances: Union[DjangoModel, List[DjangoModel]],
            base_class: Optional[Type[serializers.ModelSerializer]] = None,
            context: Optional[Dict[str, any]] = None,
            **kwargs,
    ):
        """
        Based on the provided model_instance and base_class a unique serializer
        containing the correct field type is generated.

        :param model_instance_or_instances: The instance or list of instances for which
            the serializer must be generated.
        :type model_instance_or_instances: Model
        :param base_class: The base serializer class that must be extended. For example
            common fields could be stored here.
        :type base_class: ModelSerializer
        :param context: Extra context arguments to pass to the serializers context.
        :type kwargs: dict
        :param kwargs: The kwargs are used to initialize the serializer class.
        :type kwargs: dict
        :raises ValueError: When the `get_by_model` method was not found, which could
            indicate the `ModelRegistryMixin` has not been mixed in.
        :return: The instantiated generated model serializer.
        :rtype: ModelSerializer
        """

        get_by_model = getattr(self, "get_by_model")
        if not get_by_model:
            raise ValueError(
                "The method get_by_model must exist on the registry in "
                "order to generate the serializer, maybe you forgot to "
                "extend the ModelRegistryMixin?"
            )
        if isinstance(model_instance_or_instances, list):
            instance_type = self.get_by_model(
                model_instance_or_instances[0].specific_class
            )
        else:
            instance_type = self.get_by_model(
                model_instance_or_instances.specific_class
            )
        return instance_type.get_serializer(
            model_instance_or_instances,
            base_class=base_class,
            context=context,
            **kwargs,
        )
