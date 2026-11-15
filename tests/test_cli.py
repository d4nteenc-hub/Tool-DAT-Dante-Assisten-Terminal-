import os
import tempfile
import unittest
from unittest import mock

from dat import cli, config, providers


class FakeUI:
    def __init__(self, answers=()):
        self.out, self.answers = [], list(answers)
        self.mode = self.model = None

    def say(self, kind, text):
        self.out.append((kind, text))

    def ask(self, label, secret=False):
        return self.answers.pop(0) if self.answers else None

    def set_mode(self, mode):
        self.mode = mode

    def set_model(self, provider, model):
        self.model = (provider, model)

    def status(self, text):
        pass

    def clear(self):
        self.out.append(("clear", ""))

    def kinds(self, kind):
        return [t for k, t in self.out if k == kind]


class FakeAgent:
    def __init__(self):
        self.resets = 0

    def reset(self):
        self.resets += 1


class HelperTests(unittest.TestCase):
    def test_clean_key(self):
        self.assertEqual(cli.clean_key('  "gsk_abc def"\n'), "gsk_abcdef")
        self.assertEqual(cli.clean_key("Bearer sk-123"), "sk-123")
        self.assertEqual(cli.clean_key("   "), "")

    def test_short_path(self):
        home = os.path.expanduser("~")
        self.assertEqual(cli.short_path(home), "~")
        self.assertEqual(cli.short_path(os.path.join(home, "x")), "~" + os.sep + "x")
        self.assertEqual(cli.short_path(home + "extra"), home + "extra")
        self.assertEqual(cli.short_path("/tmp"), "/tmp")


class CliTestCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        p = mock.patch.dict(os.environ, {"DAT_CONFIG": os.path.join(d.name, "c.json")})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = {"provider": "groq", "api_key": "k", "model": "m1", "mode": "fast"}


class SetupTests(CliTestCase):
    def test_detects_provider_tests_the_key_and_saves(self):
        ui = FakeUI(["  gsk_abc123 \n"])
        with mock.patch.object(cli.providers, "list_models", return_value=["openai/gpt-oss-120b", "x"]):
            out = cli.setup(ui, self.cfg, True)
        self.assertIs(out, self.cfg)
        self.assertEqual((self.cfg["provider"], self.cfg["api_key"], self.cfg["model"]),
                         ("groq", "gsk_abc123", "openai/gpt-oss-120b"))
        self.assertEqual(config.load()["api_key"], "gsk_abc123")

    def test_rejected_key_asks_again_and_ctrl_d_quits(self):
        ui = FakeUI(["gsk_bad", None])
        err = providers.ProviderError("auth", "nope", 401)
        with mock.patch.object(cli.providers, "list_models", side_effect=err):
            self.assertIsNone(cli.setup(ui, self.cfg, True))
        self.assertTrue(ui.kinds("err"))
        self.assertEqual(self.cfg["api_key"], "k")

    def test_empty_input_cancels_when_changing_the_key(self):
        ui = FakeUI([""])
        self.assertIs(cli.setup(ui, self.cfg, False), self.cfg)
        self.assertEqual(self.cfg["api_key"], "k")


class AppTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.ui = FakeUI()
        self.app = cli.App(self.ui, self.cfg)
        self.app.agent = FakeAgent()

    def test_mode_commands_switch_and_persist(self):
        self.assertIsNone(self.app.command("/think"))
        self.assertEqual((self.cfg["mode"], self.ui.mode), ("think", "think"))
        self.assertEqual(config.load()["mode"], "think")

    def test_exit_commands_stop_the_loop(self):
        for c in ("/exit", "/quit", "/q"):
            self.assertIs(self.app.command(c), False)

    def test_unknown_command_warns(self):
        self.app.command("/nope")
        self.assertIn("Unknown command /nope. Try /help.", self.ui.kinds("warn"))

    def test_clear_resets_the_agent(self):
        self.app.command("/clear")
        self.assertEqual(self.app.agent.resets, 1)

    def test_model_by_number_and_by_name(self):
        self.app.models = ["a", "b", "c"]
        self.app.command("/model 2")
        self.assertEqual(self.cfg["model"], "b")
        self.assertEqual(self.ui.model, ("groq", "b"))
        self.app.command("/model custom-x")
        self.assertEqual(config.load()["model"], "custom-x")

    def test_model_number_out_of_range_warns(self):
        self.app.models = ["a"]
        self.app.command("/model 5")
        self.assertEqual(self.cfg["model"], "m1")
        self.assertTrue(self.ui.kinds("warn"))

    def test_model_list_is_numbered_and_filterable(self):
        with mock.patch.object(cli.providers, "list_models", return_value=["gpt-a", "llama-b", "llama-c"]):
            self.app.command("/model list llama")
        self.assertEqual(self.app.models, ["llama-b", "llama-c"])
        self.assertIn(" 1) llama-b", self.ui.kinds("say")[0])


if __name__ == "__main__":
    unittest.main()
