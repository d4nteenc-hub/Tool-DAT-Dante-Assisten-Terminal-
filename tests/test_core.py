import dataclasses
import http.client
import importlib
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import dat
from dat import config, providers, shell, theme
from dat.theme import width, wrap


class Handler(BaseHTTPRequestHandler):
    calls = []
    fail_once = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        Handler.calls.append(("GET", self.path, dict(self.headers)))
        if self.headers.get("Authorization") == "Bearer bad" or self.headers.get("x-api-key") == "bad":
            return self._send(401, {"error": {"message": "Invalid API Key"}})
        self._send(200, {"data": [{"id": "models/gemini-2.5-flash"}, {"id": "text-embedding-1"},
                                  {"id": "whisper-1"}, {"id": "claude-haiku-5-5"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.calls.append(("POST", self.path, body))
        if Handler.fail_once:
            code = Handler.fail_once.pop()
            return self._send(code, {"error": {"message": "slow down"}}, {"Retry-After": "0"})
        if self.path.endswith("/messages"):
            return self._send(200, {"content": [{"type": "text", "text": "anthropic-ok"}]})
        self._send(200, {"choices": [{"message": {"content": "openai-ok"}}]})


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        cls.url = "http://127.0.0.1:%d" % cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        Handler.calls.clear()
        Handler.fail_once.clear()
        p = mock.patch.dict(os.environ, {"DAT_BASE_URL": self.url + "/v1"})
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch.object(providers, "_sleep", lambda *a, **k: False)
        s.start()
        self.addCleanup(s.stop)

    def test_detect(self):
        d = providers.detect
        self.assertEqual(d("gsk_abc"), "groq")
        self.assertEqual(d("AIzaSyXYZ"), "gemini")
        self.assertEqual(d("sk-or-v1-abc"), "openrouter")
        self.assertEqual(d("sk-ant-api03-abc"), "anthropic")
        self.assertEqual(d("sk-proj-abc"), "openai")
        self.assertEqual(d("sk-abc"), "openai")
        self.assertIsNone(d("whatever"))

    def test_list_models_filters_non_chat_and_strips_prefix(self):
        self.assertEqual(providers.list_models("gemini", "k"), ["gemini-2.5-flash", "claude-haiku-5-5"])

    def test_requests_send_a_custom_user_agent(self):
        providers.list_models("groq", "k")
        ua = Handler.calls[0][2].get("User-Agent", "")
        self.assertTrue(ua.startswith("DAT/"), ua)

    def test_auth_error_is_classified(self):
        with self.assertRaises(providers.ProviderError) as cm:
            providers.list_models("groq", "bad")
        self.assertEqual(cm.exception.kind, "auth")
        self.assertIn("Invalid API Key", cm.exception.message)

    def test_openai_chat_puts_system_first(self):
        out = providers.chat("groq", "k", "m", "SYS", [{"role": "user", "content": "hi"}])
        self.assertEqual(out, "openai-ok")
        body = Handler.calls[-1][2]
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})

    def test_anthropic_chat_uses_native_api_and_merges_roles(self):
        fake = dataclasses.replace(providers.PROVIDERS["anthropic"], base=self.url + "/v1")
        with mock.patch.dict(providers.PROVIDERS, {"anthropic": fake}):
            msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
            self.assertEqual(providers.chat("anthropic", "k", "m", "SYS", msgs), "anthropic-ok")
        body = Handler.calls[-1][2]
        self.assertEqual(body["system"], "SYS")
        self.assertEqual(len(body["messages"]), 1)

    def test_rate_limit_is_retried(self):
        Handler.fail_once.append(429)
        waits = []
        out = providers.chat("groq", "k", "m", "S", [{"role": "user", "content": "x"}],
                             on_wait=lambda s, e: waits.append(s))
        self.assertEqual(out, "openai-ok")
        self.assertEqual(len(waits), 1)

    def test_truncated_response_is_a_network_error(self):
        err = http.client.IncompleteRead(b"")
        with mock.patch.object(providers.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.list_models("groq", "k")
        self.assertEqual(cm.exception.kind, "network")

    def test_pick_default(self):
        self.assertEqual(providers.pick_default("groq", ["a", "openai/gpt-oss-120b"]), "openai/gpt-oss-120b")
        self.assertEqual(providers.pick_default("gemini", ["gemini-2.5-flash-lite", "gemini-2.5-flash"]),
                         "gemini-2.5-flash")
        self.assertEqual(providers.pick_default("openrouter", ["paid/x", "a/b:free"]), "a/b:free")
        self.assertEqual(providers.pick_default("openai", []), "gpt-4o-mini")


class ShellTests(unittest.TestCase):
    def test_output_exit_code_and_cwd(self):
        r = shell.run("echo hi; echo oops >&2; cd /tmp; exit 3", "/")
        self.assertEqual((r.code, r.output, r.cwd), (3, "hi\noops", "/tmp"))

    def test_progress_bars_keep_last_frame_and_ansi_is_stripped(self):
        r = shell.run("printf 'a\\rb\\rc\\n'; printf '\\033[31mred\\033[0m\\n'", "/tmp")
        self.assertEqual(r.output, "c\nred")

    def test_timeout_kills_the_process(self):
        r = shell.run("sleep 10", "/tmp", timeout=0.5)
        self.assertTrue(r.timed_out)

    def test_cancel(self):
        r = shell.run("sleep 10", "/tmp", cancel=lambda: True)
        self.assertTrue(r.cancelled)

    def test_stdin_is_closed_so_prompts_cannot_hang(self):
        r = shell.run("read x; echo got=$x", "/tmp", timeout=5)
        self.assertEqual(r.output, "got=")

    def test_truncate_keeps_head_and_tail(self):
        t = shell.truncate("A" * 5000 + "B" * 5000, 1000)
        self.assertTrue(t.startswith("A") and t.endswith("B") and "omitted" in t)
        self.assertLess(len(t), 1100)


class ConfigTests(unittest.TestCase):
    def test_roundtrip_permissions_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"DAT_CONFIG": os.path.join(d, "sub", "config.json")}):
                self.assertFalse(config.is_ready(config.load()))
                path = config.save({"provider": "groq", "api_key": "k", "model": "m", "mode": "think"})
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
                self.assertEqual(config.load()["mode"], "think")
                self.assertTrue(config.is_ready(config.load()))
                self.assertTrue(config.reset())
                self.assertFalse(config.is_ready(config.load()))


class PackagingTests(unittest.TestCase):
    def test_version_matches_pyproject(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('version = "%s"' % dat.__version__, text)


class WrapTests(unittest.TestCase):
    def test_rows_never_exceed_width(self):
        text = "Hello world " * 5 + "x" * 50 + " 你好世界" * 6
        for w in (12, 20, 33):
            for row in wrap([(" > ", "a"), (text, "b")], w, 3):
                self.assertLessEqual(width("".join(t for t, _ in row)), w)

    def test_text_is_preserved(self):
        rows = wrap([("one two three four five", "a")], 9)
        self.assertEqual(" ".join("".join(t for t, _ in r).strip() for r in rows), "one two three four five")


class ThemeTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(theme)

    def test_ascii_glyphs_when_the_terminal_codeset_is_not_utf(self):
        with mock.patch("locale.nl_langinfo", return_value="ANSI_X3.4-1968"):
            importlib.reload(theme)
        self.assertFalse(theme.UTF)
        self.assertTrue(all(ord(c) < 128 for c in "".join(theme.G.values())))
        self.assertTrue(all(ord(c) < 128 for row in theme.ART for c in row))


if __name__ == "__main__":
    unittest.main()
