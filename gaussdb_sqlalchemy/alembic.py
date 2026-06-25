"""
Alembic integration for GaussDB SQLAlchemy dialect.

Registers an Alembic implementation that handles M-compat (MySQL) mode
differences in ALTER TABLE syntax.
"""
from __future__ import annotations


def register_alembic_impl():
    """Register GaussDB-specific Alembic implementation."""
    try:
        from alembic.ddl import postgresql as pg_impl
        from alembic.ddl.base import ColumnType, ColumnNullable, ColumnDefault
        from sqlalchemy.ext.compiler import compiles

        # M-compat: ALTER COLUMN ... TYPE → MODIFY COLUMN
        @compiles(ColumnType, "gaussdb")
        def _gaussdb_column_type(element, compiler, **kw):
            from gaussdb_sqlalchemy.base import GaussDBDialect

            dialect = kw.get("dialect")
            compat = getattr(dialect, "gaussdb_compatibility", None) if dialect else None

            if compat == "M":
                table_name = compiler.preparer.quote(element.table_name)
                col_name = compiler.preparer.quote(element.column_name)
                col_type = element.column.type
                type_text = dialect.type_compiler_instance.process(col_type) if dialect else ""
                return f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {type_text}"

            return pg_impl.visit_column_type(element, compiler, **kw)

        @compiles(ColumnNullable, "gaussdb")
        def _gaussdb_column_nullable(element, compiler, **kw):
            dialect = kw.get("dialect")
            compat = getattr(dialect, "gaussdb_compatibility", None) if dialect else None

            if compat == "M":
                table_name = compiler.preparer.quote(element.table_name)
                col_name = compiler.preparer.quote(element.column_name)
                null_spec = "NULL" if element.existing_nullable else "NOT NULL"
                return f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {null_spec}"

            return pg_impl.visit_column_nullable(element, compiler, **kw)

    except ImportError:
        # Alembic not installed
        pass
