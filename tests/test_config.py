from __future__ import annotations

from pathlib import Path

import pytest

from buff_sentinel.config import ConfigError, load_config, load_config_dir

_ITEMS = """
  - goods_id: 100
    name: "One"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 101
    name: "Two"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 102
    name: "Three"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 103
    name: "Four"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 104
    name: "Five"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 105
    name: "Six"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 106
    name: "Seven"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 107
    name: "Eight"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 108
    name: "Nine"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 109
    name: "Ten"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
"""


def _with_items(yaml_text: str) -> str:
    return yaml_text + "\nowned:\n" + _ITEMS


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    yaml_text = """
app:
  timezone: "Asia/Shanghai"
  database_url: "sqlite:///./data/buff.db"
  log_level: "info"
llm:
  base_url: "https://llm.example.com/v1"
  api_key: "${TEST_LLM_KEY}"
  model: "gpt-x"
qq_bot:
  app_id: "app-1"
  client_secret: "secret"
  recipients: ["openid-1"]
"""
    cfg = load_config(
        _write(tmp_path, _with_items(yaml_text)),
        env={"TEST_LLM_KEY": "abc123"},
    )
    assert cfg.app.log_level == "INFO"
    assert cfg.llm.api_key == "abc123"
    assert cfg.owned[0].goods_id == 100
    assert len(cfg.owned) == 10


def test_missing_env_raises(tmp_path: Path) -> None:
    yaml_text = """
llm:
  base_url: "https://x"
  api_key: "${MISSING_KEY}"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
"""
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, _with_items(yaml_text)), env={})


def test_env_default(tmp_path: Path) -> None:
    yaml_text = """
buff:
  session_cookie: "${OPTIONAL_COOKIE:-}"
llm:
  base_url: "https://x"
  api_key: "k"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
"""
    cfg = load_config(_write(tmp_path, _with_items(yaml_text)), env={})
    assert cfg.buff.session_cookie == ""


def test_fewer_than_ten_items_rejected(tmp_path: Path) -> None:
    yaml_text = """
llm:
  base_url: "https://x"
  api_key: "k"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
owned:
  - goods_id: 1
    name: "N"
    purchase_price: 1.0
    profit_pct: 1.0
    loss_pct: 1.0
"""
    with pytest.raises(ConfigError, match="between 10 and 100"):
        load_config(_write(tmp_path, yaml_text), env={})


def test_wishlist_requires_trigger(tmp_path: Path) -> None:
    yaml_text = """
llm:
  base_url: "https://x"
  api_key: "k"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
wishlist:
  - goods_id: 1
    name: "N"
"""
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, yaml_text), env={})


def test_duplicate_goods_id_rejected(tmp_path: Path) -> None:
    yaml_text = _with_items(
        """
llm:
  base_url: "https://x"
  api_key: "k"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
wishlist:
  - goods_id: 100
    name: "Duplicate"
    target_price: 50.0
"""
    )
    with pytest.raises(ConfigError, match="duplicate goods_id"):
        load_config(_write(tmp_path, yaml_text), env={})


def test_example_config_parses(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    for name in ("app", "items", "llm", "notifiers"):
        source = root / "config" / f"{name}.example.yaml"
        (config_dir / f"{name}.yaml").write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    env = {
        "LLM_API_KEY": "env-llm-key",
        "QQ_APP_ID": "env-app-id",
        "QQ_CLIENT_SECRET": "env-secret",
        "QQ_RECIPIENT_OPENID": "env-openid",
        "BUFF_SESSION_COOKIE": "",
    }
    cfg = load_config_dir(config_dir, env=env)
    assert cfg.qq_bot.app_id == "env-app-id"
    assert len(cfg.owned) + len(cfg.wishlist) == 10
