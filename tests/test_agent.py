import unittest

from dat import agent, shell
from dat.providers import ProviderError


class FakeIO:
    def __init__(self, answers=()):
        self.out, self.asked, self.answers, self.cancel = [], [], list(answers), False

    def say(self, kind, text):
        self.out.append((kind, text))

    def ask(self, label, secret=False):
        self.asked.append(label)
        return self.answers.pop(0) if self.answers else None

    def cancelled(self):
        return self.cancel

    def status(self, text):
        pass

    def kinds(self, kind):
        return [t for k, t in self.out if k == kind]


class Harness:
    def __init__(self, replies, answers=(), mode="fast"):
        self.replies, self.calls, self.ran = list(replies), [], []
        self.io = FakeIO(answers)
        cfg = {"provider": "groq", "api_key": "k", "model": "m", "mode": mode}
        self.agent = agent.Agent(cfg, self.io, chat_fn=self.chat, run_fn=self.run)

    def chat(self, pid, key, model, system, messages, **kw):
        self.calls.append((system, list(messages)))
        if system.startswith("You classify"):
            return "YES" if "mungkin" in messages[-1]["content"] else "NO"
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def run(self, cmd, cwd, **kw):
        self.ran.append(cmd)
        for line in ("line-1", "line-2"):
            kw["on_line"](line)
        return shell.Result(0, "line-1\nline-2", cwd)


def reply(say="", commands=(), done=False, plan=None):
    import json
    d = {"say": say, "commands": list(commands), "done": done}
    if plan:
        d["plan"] = plan
    return json.dumps(d)


class ParseTests(unittest.TestCase):
    def test_json_in_fences_and_think_tags(self):
        r = agent.parse_reply('<think>hmm</think>```json\n{"say":"hi","commands":["ls"],"done":false}\n```')
        self.assertEqual((r.say, r.commands, r.done), ("hi", ["ls"], False))

    def test_plain_text_becomes_a_final_answer(self):
        r = agent.parse_reply("Just words, no JSON.")
        self.assertEqual((r.say, r.commands, r.done), ("Just words, no JSON.", [], True))

    def test_json_surrounded_by_chatter(self):
        r = agent.parse_reply('Sure! {"say":"ok","commands":[{"cmd":"pwd"}]} Hope that helps.')
        self.assertEqual(r.commands, ["pwd"])
        self.assertFalse(r.done)

    def test_yes_no_local_and_ai_fallback(self):
        yes = ["y", "ya", "iya gas!", "sikat", "oui", "はい", "好的"]
        no = ["n", "jangan", "nggak", "no way", "batal", "", "nein"]
        self.assertTrue(all(agent.interpret_yes_no(t) for t in yes))
        self.assertFalse(any(agent.interpret_yes_no(t) for t in no))
        self.assertFalse(agent.interpret_yes_no("hmm mungkin"))
        self.assertTrue(agent.interpret_yes_no("hmm mungkin", lambda t: True))
        self.assertFalse(agent.interpret_yes_no("hmm", lambda t: 1 / 0))


class AgentTests(unittest.TestCase):
    def test_runs_commands_and_feeds_output_back(self):
        h = Harness([reply("Cek.", ["df -h"]), reply("Sisa 5G.", done=True)])
        h.agent.handle("storage?")
        self.assertEqual(h.ran, ["df -h"])
        self.assertEqual(h.io.kinds("say"), ["Cek.", "Sisa 5G."])
        self.assertEqual(h.io.kinds("out"), ["line-1", "line-2"])
        fed_back = h.calls[1][1][-1]
        self.assertEqual(fed_back["role"], "user")
        self.assertIn("$ df -h\nexit: 0\nline-1", fed_back["content"])

    def test_destructive_command_asks_and_accepts_any_language(self):
        h = Harness([reply("Hapus.", ["rm -rf cache"]), reply("Beres.", done=True)], answers=["ya"])
        h.agent.handle("bersihin")
        self.assertEqual(h.io.asked, ["answer (yes/no)"])
        self.assertEqual(h.ran, ["rm -rf cache"])

    def test_declined_destructive_command_is_not_run_and_stops(self):
        h = Harness([reply("Hapus.", ["rm -rf cache"])], answers=["jangan"])
        h.agent.handle("bersihin")
        self.assertEqual(h.ran, [])
        self.assertIn("Skipped.", h.io.kinds("dim"))
        self.assertEqual(len(h.calls), 1)

    def test_unclear_answer_goes_to_the_ai_and_unclear_means_no(self):
        h = Harness([reply("x", ["rm a"])], answers=["hmm entahlah"])
        h.agent.handle("go")
        self.assertEqual(h.ran, [])
        h = Harness([reply("x", ["rm a"]), reply("ok", done=True)], answers=["hmm mungkin"])
        h.agent.handle("go")
        self.assertEqual(h.ran, ["rm a"])

    def test_blocked_command_never_runs_and_ai_is_told(self):
        h = Harness([reply("Oke.", ["rm -rf ~"]), reply("Gak bisa.", done=True)])
        h.agent.handle("hapus semua")
        self.assertEqual(h.ran, [])
        self.assertTrue(any("Blocked" in t for t in h.io.kinds("warn")))
        self.assertIn("BLOCKED", h.calls[1][1][-1]["content"])

    def test_think_mode_shows_plan_and_waits_for_approval(self):
        h = Harness([reply("Rencana.", plan=["a", "b"]), reply("Jalan.", ["echo hi"], done=True)],
                    answers=["sikat"], mode="think")
        h.agent.handle("bikin project")
        self.assertIn("THINK", h.calls[0][0])
        self.assertIn("1. a\n2. b", h.io.kinds("say")[1])
        self.assertEqual(h.ran, ["echo hi"])
        h = Harness([reply("Rencana.", plan=["a"])], answers=["no"], mode="think")
        h.agent.handle("bikin project")
        self.assertEqual(h.ran, [])

    def test_provider_error_is_reported_and_history_stays_clean(self):
        h = Harness([ProviderError("auth", "Invalid API Key", 401)])
        h.agent.handle("halo")
        self.assertIn("Key rejected", h.io.kinds("err")[0])
        self.assertEqual(h.agent.history, [])

    def test_step_limit(self):
        h = Harness([reply("again", ["echo x"])] * 20)
        h.agent.handle("loop forever")
        self.assertEqual(len(h.ran), 8)
        self.assertTrue(any("Step limit" in t for t in h.io.kinds("warn")))

    def test_cwd_persists_between_commands(self):
        h = Harness([reply("a", ["cd /tmp"]), reply("b", done=True)])
        h.agent.run_fn = lambda cmd, cwd, **kw: shell.Result(0, "", "/tmp")
        h.agent.handle("go")
        self.assertEqual(h.agent.cwd, "/tmp")
        self.assertIn("CWD: /tmp", h.calls[1][0])

    def test_system_prompt_contents(self):
        s = agent.build_system("fast", "/x")
        self.assertIn("Mode: FAST", s)
        self.assertIn("CWD: /x", s)
        self.assertIn("Reply in the user's language", s)


if __name__ == "__main__":
    unittest.main()
