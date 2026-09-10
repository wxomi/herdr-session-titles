"""Herdr Session Titles plugin package."""

from session_titles.client import HerdrClient
from session_titles.extractors import DEFAULT_EXTRACTORS, register_extractor, title_for_pane
from session_titles.extractors.base import BaseExtractor
from session_titles.sync import sync_all

__version__ = "0.4.0"

__all__ = [
    "HerdrClient",
    "BaseExtractor",
    "DEFAULT_EXTRACTORS",
    "register_extractor",
    "title_for_pane",
    "sync_all",
    "__version__",
]
