"""Strict Pydantic schemas for the runtime configuration."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AppConfig(_StrictModel):
    timezone: str = "UTC"
    database_url: str = "sqlite:///./data/buff-sentinel.db"
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper


class CollectionConfig(_StrictModel):
    interval_seconds: int = Field(default=600, ge=60, le=86400)
    # Scheduler jitter (seconds) to avoid herd + lockstep cadence.
    schedule_jitter_seconds: int = Field(default=30, ge=0, le=300)
    # Independent QQ recovery probe cadence. 0 disables the standalone job
    # (probe still runs at the end of each collection round).
    probe_interval_seconds: int = Field(default=300, ge=0, le=3600)
    snapshot_retention_days: int = Field(default=7, ge=1, le=90)
    history_retention_days: int = Field(default=90, ge=1, le=3650)
    wishlist_review_days: int = Field(default=3, ge=1, le=30)


class BuffConfig(_StrictModel):
    base_url: str = "https://buff.163.com"
    proxy_url: str = ""
    sell_order_path: str = "/api/market/goods/sell_order"
    buy_order_path: str = "/api/market/goods/buy_order"
    request_interval_ms: int = Field(default=1500, ge=0, le=60000)
    jitter_ms: int = Field(default=400, ge=0, le=60000)
    max_concurrency: int = Field(default=2, ge=1, le=8)
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=3, ge=0, le=10)
    session_cookie: str = ""
    user_agent: str = "buff-price-sentinel/0.1"


class LLMConfig(_StrictModel):
    base_url: str
    api_key: str
    # User-facing field is `model_id`; `model` is accepted as an alias for
    # backward compatibility. Internally `.model` exposes the same value.
    model_id: str = Field(
        validation_alias=AliasChoices("model_id", "model"),
    )
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=10)
    fail_open: bool = True

    @field_validator("base_url", "api_key", "model_id")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value

    @property
    def model(self) -> str:
        """Backwards-compatible accessor for the model id."""
        return self.model_id


class QQBotConfig(_StrictModel):
    token_url: str = "https://bots.qq.com/app/getAppAccessToken"
    message_base_url: str = "https://api.sgroup.qq.com"
    app_id: str
    client_secret: str
    recipients: list[str]
    # Optional lightweight probe text. If empty, the recovery probe only
    # fetches an access token; if set, it also sends this text to recipients.
    probe_message: str = ""
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=2, ge=0, le=10)

    @field_validator("app_id", "client_secret")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value is required")
        return value

    @field_validator("recipients")
    @classmethod
    def _require_recipients(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value if v and v.strip()]
        if not cleaned:
            raise ValueError("at least one recipient openid is required")
        return cleaned


class AlertConfig(_StrictModel):
    dedup_window_minutes: int = Field(default=120, ge=1, le=1440)
    goods_cooldown_minutes: int = Field(default=60, ge=0, le=1440)


class OwnedItem(_StrictModel):
    goods_id: int = Field(ge=1)
    name: str
    purchase_price: float = Field(gt=0)
    profit_pct: float | None = Field(default=None, gt=0)
    loss_pct: float | None = Field(default=None, gt=0)
    alert_above_price: float | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value

    @model_validator(mode="after")
    def _require_one_trigger(self) -> OwnedItem:
        if (
            self.profit_pct is None
            and self.loss_pct is None
            and self.alert_above_price is None
        ):
            raise ValueError(
                "owned item must define profit_pct, loss_pct, or alert_above_price"
            )
        return self


class WishlistItem(_StrictModel):
    goods_id: int = Field(ge=1)
    name: str
    target_price: float | None = Field(default=None, gt=0)
    drop_pct_24h: float | None = Field(default=None, gt=0)
    rise_pct_24h: float | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name is required")
        return value

    @model_validator(mode="after")
    def _require_one_trigger(self) -> WishlistItem:
        if (
            self.target_price is None
            and self.drop_pct_24h is None
            and self.rise_pct_24h is None
        ):
            raise ValueError(
                "wishlist item must define target_price, drop_pct_24h, or rise_pct_24h"
            )
        return self


class Config(_StrictModel):
    app: AppConfig = Field(default_factory=AppConfig)
    collection: CollectionConfig = Field(default_factory=CollectionConfig)
    buff: BuffConfig = Field(default_factory=BuffConfig)
    llm: LLMConfig
    qq_bot: QQBotConfig
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    owned: list[OwnedItem] = Field(default_factory=list)
    wishlist: list[WishlistItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_items(self) -> Config:
        total = len(self.owned) + len(self.wishlist)
        if total < 1:
            raise ValueError("config must define between 1 and 100 items")
        if total > 100:
            raise ValueError("config must define between 1 and 100 items")
        seen: set[int] = set()
        combined: list[OwnedItem | WishlistItem] = [*self.owned, *self.wishlist]
        for item in combined:
            if item.goods_id in seen:
                raise ValueError(f"duplicate goods_id: {item.goods_id}")
            seen.add(item.goods_id)
        return self
