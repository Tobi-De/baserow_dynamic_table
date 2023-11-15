from django.apps import AppConfig
from django.db.models.signals import pre_migrate

from baserow_dynamic_table.table.cache import clear_generated_model_cache


class BaserowDynamicTableConfig(AppConfig):
    name = "baserow_dynamic_table"

    def prevent_generated_model_for_registering(self):
        """
        A nasty hack that prevents a generated table model and related auto created
        models from being registered to the apps. When a model class is defined it
        will be registered to the apps, but we do not always want that to happen
        because models with the same class name can differ. They are also meant to be
        temporary. Removing the model from the cache does not work because if there
        are multiple requests at the same, it is not removed from the cache on time
        which could result in hard failures. It is also hard to extend the
        django.apps.registry.apps so this hack extends the original `register_model`
        method and it will only call the original `register_model` method if the
        model is not a generated table model.

        If anyone has a better way to prevent the models from being registered then I
        am happy to hear about it! :)
        """

        original_register_model = self.apps.register_model

        def register_model(app_label, model):
            if not hasattr(model, "_generated_table_model") and not hasattr(
                model._meta.auto_created, "_generated_table_model"
            ):
                original_register_model(app_label, model)
            else:
                # Trigger the pending operations because the original register_model
                # method also triggers them. Not triggering them can cause a memory
                # leak because everytime a table model is generated, it will register
                # new pending operations.
                self.apps.do_pending_operations(model)
                self.apps.clear_cache()

        self.apps.register_model = register_model

    def ready(self):
        self.prevent_generated_model_for_registering()

        from .fields.registries import field_converter_registry, field_type_registry

        from .fields.field_types import (
            BooleanFieldType,
            CreatedOnFieldType,
            DateFieldType,
            EmailFieldType,
            LastModifiedFieldType,
            LinkRowFieldType,
            LongTextFieldType,
            MultipleSelectFieldType,
            NumberFieldType,
            PhoneNumberFieldType,
            RatingFieldType,
            SingleSelectFieldType,
            TextFieldType,
            URLFieldType,
        )

        field_type_registry.register(TextFieldType())
        field_type_registry.register(LongTextFieldType())
        field_type_registry.register(URLFieldType())
        field_type_registry.register(EmailFieldType())
        field_type_registry.register(NumberFieldType())
        field_type_registry.register(RatingFieldType())
        field_type_registry.register(BooleanFieldType())
        field_type_registry.register(DateFieldType())

        field_type_registry.register(CreatedOnFieldType())
        field_type_registry.register(LinkRowFieldType())
        field_type_registry.register(LastModifiedFieldType())
        field_type_registry.register(SingleSelectFieldType())
        field_type_registry.register(MultipleSelectFieldType())
        field_type_registry.register(PhoneNumberFieldType())

        from .fields.field_converters import (
            FileFieldConverter,
            LinkRowFieldConverter,
            MultipleSelectFieldToSingleSelectFieldConverter,
            MultipleSelectFieldToTextFieldConverter,
            SingleSelectFieldToMultipleSelectFieldConverter,
            TextFieldToMultipleSelectFieldConverter,
        )

        field_converter_registry.register(LinkRowFieldConverter())
        field_converter_registry.register(FileFieldConverter())
        field_converter_registry.register(TextFieldToMultipleSelectFieldConverter())
        field_converter_registry.register(MultipleSelectFieldToTextFieldConverter())
        field_converter_registry.register(
            MultipleSelectFieldToSingleSelectFieldConverter()
        )
        field_converter_registry.register(
            SingleSelectFieldToMultipleSelectFieldConverter()
        )

        pre_migrate.connect(clear_generated_model_cache_receiver, sender=self)


# noinspection PyPep8Naming
def clear_generated_model_cache_receiver(sender, **kwargs):
    clear_generated_model_cache()


# noinspection PyPep8Naming
