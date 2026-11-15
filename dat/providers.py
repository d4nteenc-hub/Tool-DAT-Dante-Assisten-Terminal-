from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

UA = "DAT/1.0 (terminal assistant)"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base: str
    kind: str
    key_url: str


PROVIDERS: Dict[str, Provider] = {
    "groq": Provider("groq", "Groq", "https://api.groq.com/openai/v1", "openai",
                     "https://console.groq.com/keys"),
    "gemini": Provider("gemini", "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
                       "openai", "https://aistudio.google.com/apikey"),
    "openrouter": Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai",
                           "https://openrouter.ai/keys"),
    "openai": Provider("openai", "OpenAI", "https://api.openai.com/v1", "openai",
                       "https://platform.openai.com/api-keys"),
    "anthropic": Provider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "anthropic",
                          "https://console.anthropic.com/"),
}
ORDER = ["groq", "gemini", "openrouter", "openai", "anthropic"]


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, status: int = 0, retry_after: int = 0):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.retry_after = retry_after


def detect(key: str) -> Optional[str]:
    k = key.strip()
    if k.startswith("sk-or-"):
        return "openrouter"
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("gsk_"):
        return "groq"
    if k.startswith("AIza"):
        return "gemini"
    if k.startswith("sk-"):
        return "openai"
    return None


def _base(p: Provider) -> str:
    if p.kind == "openai":
        return (os.environ.get("DAT_BASE_URL") or p.base).rstrip("/")
    return p.base


def _headers(p: Provider, key: str) -> Dict[str, str]:
    if p.kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    h = {"Authorization": "Bearer " + key}
    if p.id == "openrouter":
        h["X-Title"] = "DAT"
    return h


def _http_error(code: int, raw: str, retry_after: Optional[str]) -> ProviderError:
    msg = ""
    try:
        j = json.loads(raw)
        if isinstance(j, list) and j:
            j = j[0]
        e = j.get("error", j) if isinstance(j, dict) else {}
        msg = e.get("message", "") if isinstance(e, dict) else str(e)
    except ValueError:
        msg = raw[:200]
    msg = (msg or "HTTP %d" % code).strip()[:300]
    if code in (401, 403):
        kind = "auth"
    elif code == 429:
        kind = "rate"
    elif code >= 500:
        kind = "server"
    elif code in (400, 404, 422):
        kind = "bad_request"
    else:
        kind = "other"
    try:
        wait = int(float(retry_after)) if retry_after else 0
    except ValueError:
        wait = 0
    return ProviderError(kind, msg, code, wait)


def _request(method: str, url: str, headers: Dict[str, str], body: Optional[dict] = None,
             timeout: int = 60) -> object:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        raise _http_error(e.code, raw, e.headers.get("Retry-After") if e.headers else None)
    except urllib.error.URLError as e:
        raise ProviderError("network", "Can't reach the server (%s)." % (e.reason,))
    except OSError as e:
        raise ProviderError("network", "Connection problem (%s)." % (e,))
    except http.client.HTTPException as e:
        raise ProviderError("network", "Connection problem (%s)." % (e,))
    except ValueError:
        raise ProviderError("other", "The server sent an unreadable response.")


def _sleep(seconds: float, cancel: Optional[Callable[[], bool]]) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cancel and cancel():
            return True
        time.sleep(0.2)
    return False


_NOT_CHAT = ("embed", "whisper", "tts", "guard", "moderation", "dall", "image", "imagen", "veo",
             "audio", "transcribe", "realtime", "aqa", "orpheus", "playai", "safeguard", "rerank",
             "lyria", "sora", "live")


def _is_chat(model_id: str) -> bool:
    m = model_id.lower()
    return not any(x in m for x in _NOT_CHAT)


def list_models(pid: str, key: str, timeout: int = 20) -> List[str]:
    p = PROVIDERS[pid]
    url = _base(p) + ("/models?limit=100" if p.kind == "anthropic" else "/models")
    j = _request("GET", url, _headers(p, key), timeout=timeout)
    items = j.get("data") if isinstance(j, dict) else j
    ids: List[str] = []
    for it in items or []:
        mid = it.get("id") if isinstance(it, dict) else None
        if isinstance(mid, str) and mid:
            ids.append(mid[7:] if mid.startswith("models/") else mid)
    return [m for m in ids if _is_chat(m)]


_PREFER = {
    "groq": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "gpt-oss", "llama-3.3", "qwen", "llama"],
    "gemini": ["gemini-2.5-flash", "gemini-flash-latest", "flash"],
    "openrouter": ["openrouter/free", ":free"],
    "openai": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini", "mini", "gpt"],
    "anthropic": ["haiku", "sonnet"],
}
_FALLBACK = {"groq": "openai/gpt-oss-120b", "gemini": "gemini-2.5-flash",
             "openrouter": "openrouter/free", "openai": "gpt-4o-mini",
             "anthropic": "claude-haiku-5-5"}
_SKIP_PREF = ("lite", "thinking", "exp", "preview", "vision", "8b")


def pick_default(pid: str, models: List[str]) -> str:
    for token in _PREFER.get(pid, []):
        if token in models:
            return token
        for m in models:
            if token in m and not any(s in m for s in _SKIP_PREF):
                return m
    if pid == "openrouter":
        free = [m for m in models if m.endswith(":free")]
        return free[0] if free else _FALLBACK["openrouter"]
    return models[0] if models else _FALLBACK.get(pid, "")


def _merge_same_role(messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(dict(m))
    return out


def _chat_once(p: Provider, key: str, model: str, system: str, messages: List[dict],
               timeout: int) -> str:
    if p.kind == "anthropic":
        body = {"model": model, "max_tokens": 2048, "system": system,
                "messages": _merge_same_role(messages)}
        j = _request("POST", _base(p) + "/messages", _headers(p, key), body, timeout)
        parts = j.get("content", []) if isinstance(j, dict) else []
        return "".join(b.get("text", "") for b in parts if isinstance(b, dict) and b.get("type") == "text")
    body = {"model": model, "messages": [{"role": "system", "content": system}] + messages}
    j = _request("POST", _base(p) + "/chat/completions", _headers(p, key), body, timeout)
    try:
        content = j["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ProviderError("other", "Unexpected response from the provider.")
    if isinstance(content, list):
        content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
    return content or ""


def chat(pid: str, key: str, model: str, system: str, messages: List[dict], *, timeout: int = 90,
         cancel: Optional[Callable[[], bool]] = None,
         on_wait: Optional[Callable[[int, ProviderError], None]] = None) -> str:
    p = PROVIDERS[pid]
    tries = 3
    for attempt in range(tries):
        try:
            return _chat_once(p, key, model, system, messages, timeout)
        except ProviderError as e:
            retryable = e.kind in ("rate", "server", "network")
            wait = e.retry_after or (2 ** attempt) * 2
            if not retryable or attempt == tries - 1 or wait > 25:
                if e.kind == "rate" and e.retry_after > 25:
                    e.message += " Try again in ~%ds." % e.retry_after
                raise
            if on_wait:
                on_wait(wait, e)
            if _sleep(wait, cancel):
                raise ProviderError("other", "Cancelled.")
    raise ProviderError("other", "Unknown error.")
