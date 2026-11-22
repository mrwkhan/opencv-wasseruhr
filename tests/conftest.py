"""Gemeinsame Einstellungen: Die bestehenden Tests prüfen deutsche Meldungen.

Die Sprache des Dienstes ist ein globaler Zustand (siehe app/sprache.py). Vor
jedem Test wird sie auf Deutsch zurückgesetzt, damit kein Test vom vorigen
abhängt. Englisch und die automatische Wahl prüft test_sprache.py."""

import pytest

from app import sprache


@pytest.fixture(autouse=True)
def deutsch():
    sprache.einstellen("de")
    yield
    sprache.einstellen("de")
