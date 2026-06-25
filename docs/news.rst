.. currentmodule:: gaussdb

.. index::
    single: Release notes
    single: News

``gaussdb`` release notes
=========================

gaussdb.0b1
^^^^^^^^^^^^^

- First public release on PyPI.
- Fixed a crash on ARM64 with some libpq builds when connection attempts fail:
    failed-connection diagnostics now use a safe snapshot instead of reading
    every libpq connection attribute.
