from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from buff_sentinel.cli import app

_ITEMS = """
  - goods_id: 42
    name: "Test"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 43
    name: "Test 2"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 44
    name: "Test 3"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 45
    name: "Test 4"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 46
    name: "Test 5"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 47
    name: "Test 6"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 48
    name: "Test 7"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 49
    name: "Test 8"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 50
    name: "Test 9"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
  - goods_id: 51
    name: "Test 10"
    purchase_price: 10.0
    profit_pct: 5.0
    loss_pct: 5.0
"""


def _write_config(tmp_path: Path) -> Path:
    body = """
llm:
  base_url: "https://x/v1"
  api_key: "k"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
owned:
""" + _ITEMS
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_validate_config(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["validate-config", "--config", str(cfg)])
    assert result.exit_code == 0
    assert '"owned": 10' in result.stdout


def test_cli_validate_config_missing_env(tmp_path: Path, monkeypatch) -> None:
    body = """
llm:
  base_url: "https://x/v1"
  api_key: "${DEFINITELY_MISSING_KEY}"
  model: "m"
qq_bot:
  app_id: "a"
  client_secret: "s"
  recipients: ["o1"]
owned:
""" + _ITEMS
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body, encoding="utf-8")
    monkeypatch.delenv("DEFINITELY_MISSING_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["validate-config", "--config", str(cfg)])
    assert result.exit_code == 2
