from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"provider": "", "api_key": "", "model": "", "mode": "fast"}


def config_path() -> Path:
    env = os.environ.get("DAT_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "dat" / "config.json"


def load() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS and isinstance(v, str)})
    if cfg["mode"] not in ("fast", "think"):
        cfg["mode"] = "fast"
    return cfg


def save(cfg: dict) -> Path:
    path = config_path()
    created = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created:
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}, f, indent=2)
    os.replace(tmp, path)
    return path


def is_ready(cfg: dict) -> bool:
    return bool(cfg.get("provider") and cfg.get("api_key") and cfg.get("model"))


def reset() -> bool:
    try:
        config_path().unlink()
        return True
    except OSError:
        return False
