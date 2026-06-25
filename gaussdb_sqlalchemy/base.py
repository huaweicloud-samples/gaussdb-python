"""
SQLAlchemy dialect for GaussDB using the gaussdb (psycopg3 fork) DBAPI.

This dialect connects to GaussDB via the gaussdb Python package (a fork of
psycopg3 that uses libpq).  It auto-detects the database compatibility mode
(A=Oracle, B=MySQL, M=MySQL) and adapts SQL generation accordingly.
"""
from __future__ import annotations

import re

from sqlalchemy.dialects.postgresql.base import (
    PGDialect,
    PGDDLCompiler,
    PGTypeCompiler,
    PGIdentifierPreparer,
    PGExecutionContext,
    PGCompiler,
)
from sqlalchemy import schema as sa_schema
from sqlalchemy import types as sqltypes
from sqlalchemy import text
from sqlalchemy.sql import expression
from sqlalchemy.sql import operators
from sqlalchemy.sql.compiler import OPERATORS
from sqlalchemy.engine import reflection

# ── compatibility detection ──────────────────────────────────────────────────

_COMPAT_CACHE: dict[str, str] = {}


def _detect_compatibility(connection) -> str:
    """Return 'A', 'B', or 'M' based on datcompatibility."""
    cache_key = str(connection.engine.url)
    if cache_key in _COMPAT_CACHE:
        return _COMPAT_CACHE[cache_key]
    try:
        row = connection.execute(
            text(
                "select datcompatibility from pg_database "
                "where datname = current_database()"
            )
        ).scalar_one()
        compat = str(row).strip().upper()[:1]
        if compat not in ("A", "B", "M", "P"):
            compat = "A"
        if compat == "P":  # 'pg' mode → treat as A
            compat = "A"
    except Exception:
        compat = "A"
    _COMPAT_CACHE[cache_key] = compat
    return compat


# ── Type compiler ────────────────────────────────────────────────────────────


class GaussDBTypeCompiler(PGTypeCompiler):
    """Adjust DDL type generation for M-compat (MySQL) mode."""

    def visit_TIMESTAMP(self, type_, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            # M mode: always emit TIMESTAMP(6) for microsecond precision
            return "TIMESTAMP(6)"
        return super().visit_TIMESTAMP(type_, **kw)

    def visit_large_binary(self, type_, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            return "BLOB"
        return super().visit_large_binary(type_, **kw)


# ── DDL compiler ─────────────────────────────────────────────────────────────


class GaussDBDDLCompiler(PGDDLCompiler):
    """Adjust DDL for M-compat (MySQL) mode."""

    def get_column_specification(self, column, **kw):
        compat = self.dialect.gaussdb_compatibility
        # M mode: INTEGER AUTO_INCREMENT instead of SERIAL for PK
        if compat == "M" and column.autoincrement and column.primary_key:
            if isinstance(column.type, sqltypes.Integer):
                coltype = self.dialect.type_compiler_instance.process(
                    sqltypes.Integer()
                )
                default = " AUTO_INCREMENT"
                colname = self.preparer.quote(column.name)
                return f"{colname} {coltype} NOT NULL{default}"
        return super().get_column_specification(column, **kw)

    def visit_create_table(self, create, **kw):
        return super().visit_create_table(create, **kw)

    def visit_column(self, column, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M" and column.autoincrement and column.primary_key:
            if isinstance(column.type, sqltypes.Integer):
                # Already handled in get_column_specification
                return self.get_column_specification(column, **kw)
        return super().visit_column(column, **kw)

    def visit_alter_column(self, alter, **kw):
        compat = self.dialect.gaussdb_compatibility
        if compat == "M":
            return self._visit_alter_column_m(alter, **kw)
        return super().visit_alter_column(alter, **kw)

    def _visit_alter_column_m(self, alter, **kw):
        """M-compat ALTER COLUMN uses MODIFY COLUMN syntax."""
        column = alter.column
        col_name = self.preparer.quote(column.name)

        if alter.modify_type is not None:
            col_type = self.dialect.type_compiler_instance.process(
                alter.modify_type
            )
            null_spec = "" if column.nullable else " NOT NULL"
            return f"ALTER TABLE {self.preparer.quote(alter.table.name)} " \
                   f"MODIFY COLUMN {col_name} {col_type}{null_spec}"

        if alter.modify_nullable is not None:
            null_spec = "NULL" if alter.modify_nullable else "NOT NULL"
            return f"ALTER TABLE {self.preparer.quote(alter.table.name)} " \
                   f"MODIFY COLUMN {col_name} {null_spec}"

        return super().visit_alter_column(alter, **kw)


# ── Identifier preparer ──────────────────────────────────────────────────────


class GaussDBIdentifierPreparer(PGIdentifierPreparer):
    """Use backticks for M-compat (MySQL) mode."""

    def __init__(self, dialect, **kwargs):
        super().__init__(dialect, **kwargs)
        compat = getattr(dialect, "gaussdb_compatibility", None)
        if compat == "M":
            self.identifier_quote_char = "`"
            self.reserved_words.update(
                [
                    "auto_increment", "engine", "charset", "collate",
                    "comment", "default", "key", "primary",
                ]
            )


# ── SQL compiler (concat fix) ────────────────────────────────────────────────


class GaussDBCompiler(PGCompiler):
    """Replace || with CONCAT() in M-compat mode."""

    def visit_expression_clauselist(self, clauselist, **kw):
        compat = getattr(self.dialect, "gaussdb_compatibility", None)
        if compat == "M":
            # Check if this is a concat operation
            if clauselist.operator is operators.concat_op:
                return self._m_concat(clauselist, **kw)
        return super().visit_expression_clauselist(clauselist, **kw)

    def _m_concat(self, clauselist, **kw):
        args = []
        for clause in clauselist.clauses:
            args.append(self.process(clause, **kw))
        return "CONCAT(" + ", ".join(args) + ")"


# ── Execution context (M-compat lastrowid) ───────────────────────────────────


class GaussDBMExecutionContext(PGExecutionContext):
    """Get auto-increment ID via LAST_INSERT_ID() in M-compat mode."""

    def get_lastrowid(self):
        try:
            cursor = self.cursor
            cursor.execute("select last_insert_id()")
            row = cursor.fetchone()
            if row and row[0] is not None:
                val = row[0]
                # Handle Java BigInteger from JDBC (shouldn't happen with psycopg3)
                if hasattr(val, "bit_length"):
                    return int(str(val))
                return int(val)
        except Exception:
            pass
        return None


# ── Dialect ──────────────────────────────────────────────────────────────────


class GaussDBDialect(PGDialect):
    """SQLAlchemy dialect for GaussDB using the gaussdb (psycopg3) DBAPI."""

    # Use psycopg3-style connection
    driver = "gaussdb"
    name = "gaussdb"

    ddl_compiler = GaussDBDDLCompiler
    type_compiler = GaussDBTypeCompiler
    preparer = GaussDBIdentifierPreparer
    statement_compiler = GaussDBCompiler

    supports_statement_cache = True
    supports_native_enum = True
    supports_native_boolean = True
    supports_smallserial = True
    supports_sequences = True
    sequences_optional = True
    postfetch_lastrowid = False
    default_paramstyle = "pyformat"

    # Disable HSTORE (not assumed for lightweight GaussDB)
    use_native_hstore = False
    postgresql_compat_version = (9, 2)

    # GaussDB compatibility mode: 'A', 'B', or 'M'
    gaussdb_compatibility = None

    # Register GaussDB M-compat binary types for reflection
    ischema_names = dict(PGDialect.ischema_names)
    ischema_names["blob"] = sqltypes.LargeBinary
    ischema_names["longblob"] = sqltypes.LargeBinary

    # ── DBAPI ────────────────────────────────────────────────────────────────

    @classmethod
    def import_dbapi(cls):
        """Import the gaussdb (psycopg3 fork) DBAPI module."""
        try:
            import gaussdb   # noqa: F401
            import gaussdb.dbapi20  # noqa: F401
            return gaussdb.dbapi20
        except ImportError:
            try:
                import psycopg
                import psycopg.dbapi20
                return psycopg.dbapi20
            except ImportError:
                raise ImportError(
                    "The gaussdb dialect requires the 'gaussdb' package "
                    "(or 'psycopg' as fallback). "
                    "Install with: pip install gaussdb"
                )

    # ── Connection ───────────────────────────────────────────────────────────

    def create_connect_args(self, url):
        """Convert SQLAlchemy URL to gaussdb connect() kwargs."""
        opts = url.translate_connect_args(username="user", database="dbname")
        opts.update(url.query)

        # Remove SQLAlchemy-specific params
        opts.pop("host", None)
        opts.pop("port", None)
        opts.pop("user", None)
        opts.pop("password", None)
        opts.pop("dbname", None)
        opts.pop("database", None)

        # Build conninfo string for gaussdb.connect()
        parts = []
        if url.host:
            parts.append(f"host={url.host}")
        if url.port:
            parts.append(f"port={url.port}")
        if url.username:
            parts.append(f"user={url.username}")
        if url.password:
            parts.append(f"password={url.password}")
        if url.database:
            parts.append(f"dbname={url.database}")

        # Pass through extra params (sslmode, etc.)
        for key, value in opts.items():
            parts.append(f"{key}={value}")

        conninfo = " ".join(parts)
        return ([conninfo], {})

    def do_execute(self, cursor, statement, parameters, context=None):
        cursor.execute(statement, parameters)

    # ── Initialization ───────────────────────────────────────────────────────

    def initialize(self, connection):
        super().initialize(connection)
        self.gaussdb_compatibility = _detect_compatibility(connection)
        self._apply_compatibility_features()

    def _apply_compatibility_features(self):
        """Apply mode-specific dialect settings."""
        if self.gaussdb_compatibility == "M":
            # M mode: no RETURNING, use LAST_INSERT_ID
            self.insert_returning = False
            self.postfetch_lastrowid = True
            self.execution_ctx_cls = GaussDBMExecutionContext
            # M mode: no native boolean (uses TINYINT)
            self.supports_native_boolean = False
        else:
            self.insert_returning = True
            self.postfetch_lastrowid = False
            self.supports_native_boolean = True

    # ── Isolation level ──────────────────────────────────────────────────────

    def set_isolation_level(self, connection, level):
        compat = self.gaussdb_compatibility
        if compat == "M":
            # M mode: COMMIT before SET to avoid transaction conflicts
            connection.commit()
            # M mode: no "AS" keyword in SET SESSION CHARACTERISTICS
            level = level.upper().replace(" ", " ")
            connection.execute(
                text(f"SET SESSION TRANSACTION ISOLATION LEVEL {level}")
            )
        else:
            super().set_isolation_level(connection, level)

    # ── Reflection overrides for M-compat ────────────────────────────────────

    @reflection.cache
    def get_columns(self, connection, table_name, schema=None, **kw):
        compat = self.gaussdb_compatibility
        if compat == "M":
            return self._get_columns_m(connection, table_name, schema, **kw)
        return super().get_columns(connection, table_name, schema, **kw)

    def _get_columns_m(self, connection, table_name, schema=None, **kw):
        """M-compat column reflection: map blob→LargeBinary."""
        columns = super().get_columns(connection, table_name, schema, **kw)
        for col in columns:
            type_obj = col["type"]
            type_str = str(type_obj).lower()
            # M mode: blob types should be LargeBinary
            if "bytea" in type_str or "blob" in type_str:
                col["type"] = sqltypes.LargeBinary()
        return columns


# ── Registration ─────────────────────────────────────────────────────────────


def register_dialect():
    """Register the GaussDB dialect with SQLAlchemy."""
    from sqlalchemy.dialects import registry

    registry.register(
        "gaussdb", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
    registry.register(
        "gaussdb.psycopg", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
    registry.register(
        "gaussdb.gaussdb", "gaussdb_sqlalchemy.base", "GaussDBDialect"
    )
