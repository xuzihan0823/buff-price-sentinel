"""YAML loader with `${ENV[:-default]}` interpolation and file splitting.

Supports two layouts:

1. Single main file with an optional `includes` list (paths relative to the
   main file). Included files are deep-merged into the main mapping.
2. A config *directory* containing `app.yaml`, `items.yaml`, `llm.yaml`, and
   `notifiers.yaml`, deep-merged in that order.

Real local config files (`*.yaml`) are gitignored; only `*.example.yaml` is
tracked.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from buff_sentinel.config.schema import Config

_ENV_RE = re.compile(
    r"\$\{(?P<name>[A-Z_][A-Z0-9_]*)(?::-(?P<default>[^}]*))?\}"
)

# Known split-file names, merged in this order when loading a directory.
DIRECTORY_FILES: tuple[str, ...] = (
    "app.yaml",
    "items.yaml",
    "llm.yaml",
    "notifiers.yaml",
)


class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


def _interpolate(value: str, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        if name in env:
            return env[name]
        if default is not None:
            return default
        raise ConfigError(f"environment variable {name!r} is not set")

    return _ENV_RE.sub(replace, value)


def _walk(node: Any, env: dict[str, str]) -> Any:
    if isinstance(node, str):
        return _interpolate(node, env)
    if isinstance(node, list):
        return [_walk(item, env) for item in node]
    if isinstance(node, dict):
        return {key: _walk(val, env) for key, val in node.items()}
    return node


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into `base` (overlay wins on conflict).

    Lists are replaced wholesale (owned/wishlist lists come from a single
    file, so concatenation semantics would be surprising).
    """
    result = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"failed to parse YAML {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"top-level YAML in {path} must be a mapping")
    return raw


def _resolve_includes(
    main_path: Path, raw: dict[str, Any]
) -> dict[str, Any]:
    includes = raw.pop("includes", None)
    if includes is None:
        return raw
    if not isinstance(includes, list):
        raise ConfigError("'includes' must be a list of paths")
    merged: dict[str, Any] = {}
    base_dir = main_path.parent
    for entry in includes:
        if not isinstance(entry, str):
            raise ConfigError(f"invalid include entry: {entry!r}")
        inc_path = (base_dir / entry).expanduser()
        inc_raw = _read_yaml(inc_path)
        merged = _deep_merge(merged, inc_raw)
    return _deep_merge(merged, raw)


def load_config(path: str | Path, env: dict[str, str] | None = None) -> Config:
    file_path = Path(path).expanduser()
    raw = _read_yaml(file_path)
    raw = _resolve_includes(file_path, raw)

    env_map = dict(os.environ) if env is None else dict(env)
    resolved = _walk(raw, env_map)

    try:
        return Config.model_validate(resolved)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_config_dir(
    directory: str | Path, env: dict[str, str] | None = None
) -> Config:
    """Load and merge the four known split files from a directory."""
    dir_path = Path(directory).expanduser()
    if not dir_path.is_dir():
        raise ConfigError(f"config directory not found: {dir_path}")
    merged: dict[str, Any] = {}
    found_any = False
    for name in DIRECTORY_FILES:
        candidate = dir_path / name
        if not candidate.exists():
            continue
        found_any = True
        merged = _deep_merge(merged, _read_yaml(candidate))
    if not found_any:
        raise ConfigError(
            f"no config files ({', '.join(DIRECTORY_FILES)}) found in {dir_path}"
        )
    env_map = dict(os.environ) if env is None else dict(env)
    resolved = _walk(merged, env_map)
    try:
        return Config.model_validate(resolved)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def load_config_any(
    path: str | Path | None,
    *,
    config_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Pick the directory loader when `config_dir` is set, else the file loader."""
    if config_dir:
        return load_config_dir(config_dir, env=env)
    if path is None:
        raise ConfigError("no config path or directory provided")
    p = Path(path).expanduser()
    if p.is_dir():
        return load_config_dir(p, env=env)
    return load_config(p, env=env)
