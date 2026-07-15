"""Configuration package."""

from __future__ import annotations

from buff_sentinel.config.loader import (
    ConfigError,
    load_config,
    load_config_any,
    load_config_dir,
)
from buff_sentinel.config.schema import (
    AlertConfig,
    AppConfig,
    BuffConfig,
    CollectionConfig,
    Config,
    LLMConfig,
    OwnedItem,
    QQBotConfig,
    WishlistItem,
)

__all__ = [
    "AlertConfig",
    "AppConfig",
    "BuffConfig",
    "CollectionConfig",
    "Config",
    "ConfigError",
    "LLMConfig",
    "OwnedItem",
    "QQBotConfig",
    "WishlistItem",
    "load_config",
    "load_config_any",
    "load_config_dir",
]
