from django.db.models import Expression, Value, Field, F


class FileNameContainsExpr(Expression):
    # fmt: off
    template = (
        f"""
        EXISTS(
            SELECT attached_files ->> 'visible_name'
            FROM JSONB_ARRAY_ELEMENTS(%(field_name)s) as attached_files
            WHERE UPPER(attached_files ->> 'visible_name') LIKE UPPER(%(value)s)
        )
        """  # nosec B608
    )

    # fmt: on

    def __init__(self, field_name: F, value: Value, output_field: Field):
        super().__init__(output_field=output_field)
        self.field_name = field_name
        self.value = value

    def resolve_expression(
            self, query=None, allow_joins=True, reuse=None, summarize=False, for_save=False
    ):
        c = self.copy()
        c.is_summary = summarize

        c.field_name = self.field_name.resolve_expression(
            query, allow_joins, reuse, summarize, for_save
        )

        c.value = self.value.resolve_expression(
            query, allow_joins, reuse, summarize, for_save
        )

        return c

    def as_sql(self, compiler, connection, template=None):
        sql_value, params_value = compiler.compile(self.value)

        template = template or self.template
        data = {
            "field_name": f'"{self.field_name.field.column}"',
            "value": sql_value,
        }
        return template % data, params_value
