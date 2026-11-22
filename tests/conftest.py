"""Shared settings.

The service language is global state (see app/i18n.py). Before every test it is
reset to English, so no test depends on the one before. German and the
automatic choice are tested in test_i18n.py."""

import pytest

from app import i18n


@pytest.fixture(autouse=True)
def english():
    i18n.configure("en")
    yield
    i18n.configure("en")
