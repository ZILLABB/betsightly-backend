"""BetSightly basketball namespace.

Offline research modules are deliberately dependency-light. The older names
remain lazily importable for compatibility, but no model or network client
loads merely because an offline research module is imported.
"""
from __future__ import annotations

from importlib import import_module

__version__ = "1.1.0"

__all__ = [
    "NBADataFetcher",
    "BasketballFeatureEngineer",
    "BasketballModelFactory",
    "BasketballPredictionService",
]

_LEGACY_IMPORTS = {
    "NBADataFetcher": "basketball.data_fetcher",
    "BasketballFeatureEngineer": "basketball.feature_engineering",
    "BasketballModelFactory": "basketball.models",
    "BasketballPredictionService": "basketball.prediction_service",
}


def __getattr__(name: str):
    module = _LEGACY_IMPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)
