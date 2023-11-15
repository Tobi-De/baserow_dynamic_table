from io import BytesIO

from baserow_dynamic_table.fields.models import (
    Field,
    SelectOption,
)
from baserow_dynamic_table.fields.registries import (
    field_type_registry,
)
from baserow_dynamic_table.table.handler import TableHandler
from baserow_dynamic_table.table.models import Table
from django.contrib.auth import get_user_model
from django.db import transaction
from faker import Faker

User = get_user_model()


@transaction.atomic
def load_test_data():
    fake = Faker()
    print("Add basic data...")

    user = User.objects.get(email="admin@baserow_dynamic_table_dynamic_table_dynamic_table.io")

    try:
        products_table = Table.objects.get(name="Products")
    except Table.DoesNotExist:
        products_table = TableHandler().create_table_and_fields(
            user,
            name="Products",
            fields=[
                ("Name", "text", {}),
                (
                    "Category",
                    "single_select",
                    {},
                ),
                ("Notes", "long_text", {"field_options": {"width": 400}}),
            ],
        )

        select_field = Field.objects.get(table=products_table, name="Category")
        select_by_name = {}

        for order, option in enumerate(
                [
                    {"color": "dark-green", "value": "Fruit & Vegetable"},
                    {"color": "light-orange", "value": "Dairy"},
                    {"color": "dark-red", "value": "Meat"},
                    {"color": "blue", "value": "Fish"},
                    {"color": "dark-gray", "value": "Bakery"},
                    {"color": "dark-blue", "value": "Beverage"},
                    {"color": "light-green", "value": "Grocery"},
                ]
        ):
            select_option = SelectOption.objects.create(
                field=select_field,
                order=order,
                value=option["value"],
                color=option["color"],
            )
            select_by_name[select_option.value] = select_option.id

        data = [
            ("Bread", select_by_name["Bakery"], fake.sentence(nb_words=10)),
            ("Croissant", select_by_name["Bakery"], fake.sentence(nb_words=10)),
            ("Vine", select_by_name["Beverage"], fake.sentence(nb_words=10)),
            ("Beer", select_by_name["Beverage"], fake.sentence(nb_words=5)),
            ("Milk", select_by_name["Dairy"], fake.sentence(nb_words=10)),
            ("Cheese", select_by_name["Dairy"], fake.sentence(nb_words=10)),
            ("Butter", select_by_name["Dairy"], fake.sentence(nb_words=15)),
            ("Fish", select_by_name["Fish"], fake.sentence(nb_words=10)),
            ("Apple", select_by_name["Fruit & Vegetable"], fake.sentence(nb_words=10)),
            ("Grapes", select_by_name["Fruit & Vegetable"], fake.sentence(nb_words=3)),
            ("Carrot", select_by_name["Fruit & Vegetable"], fake.sentence(nb_words=10)),
            ("Onion", select_by_name["Fruit & Vegetable"], fake.sentence(nb_words=10)),
            ("Flour", select_by_name["Grocery"], fake.sentence(nb_words=10)),
            ("Honey", select_by_name["Grocery"], fake.sentence(nb_words=5)),
            ("Oil", select_by_name["Grocery"], fake.sentence(nb_words=10)),
            ("Pork", select_by_name["Meat"], fake.sentence(nb_words=10)),
            ("Beef", select_by_name["Meat"], fake.sentence(nb_words=5)),
            ("Chicken", select_by_name["Meat"], fake.sentence(nb_words=10)),
            ("Rabbit", select_by_name["Meat"], fake.sentence(nb_words=10)),
        ]

        RowHandler().import_rows(user, products_table, data, send_realtime_update=False)

    try:
        suppliers_table = Table.objects.get(name="Suppliers", database=database)
    except Table.DoesNotExist:
        suppliers_table = TableHandler().create_table_and_fields(
            user,
            database,
            name="Suppliers",
            fields=[
                ("Name", "text", {}),
                ("Products", "link_row", {"link_row_table": products_table}),
                ("Production", "rating", {}),
                ("Certification", "multiple_select", {}),
                ("Image", "file", {}),
                ("Notes", "long_text", {"field_options": {"width": 400}}),
            ],
        )

        for i in range(20):
            image = fake.image()
            UserFileHandler().upload_user_file(user, f"image_{i}.png", BytesIO(image))

        products = products_table.get_model(attribute_names=True)

        select_field = Field.objects.get(table=suppliers_table, name="Certification")
        for order, option in enumerate(
                [
                    {"color": "dark-green", "value": "Organic"},
                    {"color": "light-orange", "value": "Fair trade"},
                    {"color": "light-green", "value": "Natural"},
                    {"color": "light-blue", "value": "Animal protection"},
                    {"color": "blue", "value": "Eco"},
                    {"color": "dark-blue", "value": "Equitable"},
                ]
        ):
            select_option = SelectOption.objects.create(
                field=select_field,
                order=order,
                value=option["value"],
                color=option["color"],
            )
            select_by_name[select_option.value] = select_option.id

        products_by_name = {p.name: p.id for p in products.objects.all()}
        certif_by_name = {p.value: p.id for p in select_field.select_options.all()}

        image_field = Field.objects.get(table=suppliers_table, name="Image")
        file_field_type = field_type_registry.get("file")

        cache = {}

        random_file_1 = file_field_type.random_value(image_field, fake, cache)
        random_file_2 = file_field_type.random_value(image_field, fake, cache)
        random_file_3 = file_field_type.random_value(image_field, fake, cache)
        random_file_4 = file_field_type.random_value(image_field, fake, cache)

        data = [
            (
                "The happy cow",
                [products_by_name["Milk"], products_by_name["Butter"]],
                3,
                [certif_by_name["Animal protection"]],
                random_file_1,
                "Animals here are happy.",
            ),
            (
                "Jack's farm",
                [
                    products_by_name["Carrot"],
                    products_by_name["Onion"],
                    products_by_name["Chicken"],
                ],
                5,
                [certif_by_name["Organic"], certif_by_name["Equitable"]],
                random_file_2,
                "Good guy.",
            ),
            (
                "Horse & crocodile",
                [products_by_name["Beef"]],
                2,
                [certif_by_name["Fair trade"]],
                random_file_3,
                "",
            ),
            (
                "Vines LTD",
                [products_by_name["Vine"], products_by_name["Grapes"]],
                4,
                [
                    certif_by_name["Organic"],
                    certif_by_name["Natural"],
                ],
                random_file_4,
                "Excellent white & red wines.",
            ),
        ]

        RowHandler().import_rows(
            user, suppliers_table, data, send_realtime_update=False
        )

    try:
        retailers_table = Table.objects.get(name="Retailers", database=database)
    except Table.DoesNotExist:
        retailers_table = TableHandler().create_table_and_fields(
            user,
            database,
            name="Retailers",
            fields=[
                ("Name", "text", {}),
                ("Suppliers", "link_row", {"link_row_table": suppliers_table}),
                ("Rating", "rating", {}),
                ("Notes", "long_text", {"field_options": {"width": 400}}),
            ],
        )

        suppliers = suppliers_table.get_model(attribute_names=True)
        suppliers_by_name = {p.name: p.id for p in suppliers.objects.all()}

        data = [
            (
                "All from the farm",
                [suppliers_by_name["The happy cow"], suppliers_by_name["Jack's farm"]],
                3,
                fake.sentence(nb_words=10),
            ),
            (
                "My little supermarket",
                [suppliers_by_name["Vines LTD"]],
                1,
                fake.sentence(nb_words=10),
            ),
            (
                "Organic4U",
                [suppliers_by_name["The happy cow"]],
                5,
                fake.sentence(nb_words=10),
            ),
            (
                "Ecomarket",
                [
                    suppliers_by_name["Horse & crocodile"],
                    suppliers_by_name["Jack's farm"],
                ],
                3,
                fake.sentence(nb_words=10),
            ),
            (
                "Welcome to the farm",
                [suppliers_by_name["The happy cow"]],
                4,
                fake.sentence(nb_words=10),
            ),
        ]

        RowHandler().import_rows(
            user, retailers_table, data, send_realtime_update=False
        )
