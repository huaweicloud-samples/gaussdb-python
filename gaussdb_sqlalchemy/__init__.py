"""
SQLAlchemy dialect for Huawei GaussDB, built on the gaussdb (psycopg3 fork) driver.

Supports A (Oracle), B (MySQL), and M (MySQL) compatibility modes.
"""
from __future__ import annotations

from .base import GaussDBDialect, register_dialect
from .alembic import register_alembic_impl

register_dialect()
register_alembic_impl()

__all__ = ["GaussDBDialect"]
__version__ = "0.1.0"
