"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

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
from buff_sentinel.storage.database import Database
from buff_sentinel.storage.repository import Repository


@pytest.fixture
def in_memory_db() -> Database:
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


@pytest.fixture
def repository(in_memory_db: Database) -> Repository:
    return Repository(in_memory_db)


@pytest.fixture
def sample_config() -> Config:
    return Config(
        app=AppConfig(),
        collection=CollectionConfig(),
        buff=BuffConfig(request_interval_ms=0, jitter_ms=0),
        llm=LLMConfig(
            base_url="https://llm.example.com/v1",
            api_key="test-key",
            model_id="test-model",
            timeout_seconds=5.0,
            max_retries=1,
            fail_open=True,
        ),
        qq_bot=QQBotConfig(
            token_url="https://bots.qq.com/app/getAppAccessToken",
            message_base_url="https://api.sgroup.qq.com",
            app_id="app-123",
            client_secret="secret-abc",
            recipients=["openid-user-1"],
            timeout_seconds=5.0,
            max_retries=1,
        ),
        alerts=AlertConfig(),
        owned=[
            OwnedItem(
                goods_id=762000 + index,
                name="Owned Skin" if index == 0 else f"Owned Skin {index}",
                purchase_price=100.0,
                profit_pct=10.0,
                loss_pct=10.0,
            )
            for index in range(0, 9)
        ],
        wishlist=[
            WishlistItem(
                goods_id=900000,
                name="Wishlist Skin",
                target_price=50.0,
                drop_pct_24h=8.0,
            )
        ],
    )
