"""
Timezone utility functions.
"""

# Copyright (C) 2020 The Psycopg Team

from __future__ import annotations

import logging
import sys
from datetime import timezone, tzinfo

if sys.version_info >= (3, 9):
    from zoneinfo import ZoneInfo
else:
    from backports.zoneinfo import ZoneInfo

from .pq.abc import PGconn

logger = logging.getLogger("gaussdb")

_timezones: dict[bytes | None, tzinfo] = {
    None: timezone.utc,
    b"UTC": timezone.utc,
}


def get_tzinfo(pgconn: PGconn | None) -> tzinfo:
    """Return the Python timezone info of the connection's timezone."""
    try:
        tzname = pgconn.exec_(b"SHOW TimeZone").get_value(0, 0) if pgconn else None
        return _timezones[tzname]
    except KeyError:
        sname = tzname.decode() if tzname else "UTC"
        try:
            zi: tzinfo = ZoneInfo(sname)
        except (KeyError, OSError):
            logger.warning("unknown GaussDB timezone: %r; will use UTC", sname)
            zi = timezone.utc
        except Exception as ex:
            logger.warning(
                "error handling GaussDB timezone: %r; will use UTC (%s - %s)",
                sname,
                type(ex).__name__,
                ex,
            )
            zi = timezone.utc

        _timezones[tzname] = zi
        return zi
