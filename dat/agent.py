from __future__ import annotations

import json
import os
import platform
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import providers, safety, shell
from .providers import ProviderError

SYSTEM = """You are DAT (Dante Assistant Terminal). You operate the user's terminal by running shell commands.

Style: direct, no greetings, no filler, no apologies. Short sentences. Reply in the user's language.

Output: reply with ONE JSON object and nothing else:
{"say": "short message for the user", "commands": ["cmd1", "cmd2"], "done": false}
- commands run in order in one persistent shell (cd persists). Max 5 per turn. Non-interactive only: use -y flags, no editors, no pagers, no prompts. Background jobs: nohup cmd >/dev/null 2>&1 &
- After they run you get exit codes and output. Keep going until the task is finished, then set "done": true and put a one-line result in "say".
- No command needed (chat, explanation, question)? Use "commands": [] and "done": true.
- Never invent output. If a command fails, read the error and fix it, or say why.
- Destructive commands (delete, overwrite, uninstall, force) are allowed. The user is asked to confirm automatically, so never ask yourself.
- Never request or print secrets. Never run commands that hang in the foreground (servers, top, watch).
Example: user "storage left?" -> {"say": "Checking.", "commands": ["df -h ~"], "done": false}
then, after output -> {"say": "5.8G free of 110G.", "commands": [], "done": true}

Environment:
%s
%s"""

FAST_EXTRA = "Mode: FAST. Act immediately. No plan."
THINK_EXTRA = ('Mode: THINK. For any task that needs commands, first reply with a plan and no commands:\n'
               '{"say": "...", "plan": ["step 1", "step 2"], "commands": [], "done": false}\n'
               'Wait for "Plan approved", then execute. Skip the plan for simple questions.')
TERMUX_EXTRA = ("Termux: no root or sudo. Install with `pkg install -y NAME`. Shared storage is ~/storage "
                "(needs termux-setup-storage); Android files are under /sdcard.")

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")

YES = {"y", "yes", "yeah", "yep", "yup", "ok", "okay", "sure", "go", "ya", "yaa", "yaaa", "iya", "iyaa",
       "yoi", "yok", "oke", "sip", "siap", "gas", "gass", "gaskan", "lanjut", "lanjutkan", "sikat",
       "hajar", "jalan", "jalankan", "jalanin", "boleh", "si", "sí", "claro", "vale", "oui", "ja",
       "da", "hai", "sim", "evet", "tamam", "はい", "是", "是的", "好", "好的", "可以", "对", "네", "예", "نعم"}
NO = {"n", "no", "nope", "nah", "nggak", "nggk", "ngga", "gak", "gk", "ga", "tidak", "tdk", "jangan",
      "batal", "batalkan", "cancel", "stop", "skip", "non", "nein", "nao", "não", "нет", "net", "不",
      "不要", "不行", "不用", "いいえ", "아니", "아니요", "لا", "hayır", "hayir"}


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def env_info(cwd: str) -> str:
    return "\n".join([
        "OS: %s %s (%s)" % (platform.system(), platform.release(), platform.machine()),
        "Termux: " + ("yes" if is_termux() else "no"),
        "Shell: " + os.path.basename(shell.shell_path()),
        "Home: " + os.path.expanduser("~"),
        "CWD: " + cwd,
        "Date: " + time.strftime("%Y-%m-%d %H:%M %Z"),
    ])


def build_system(mode: str, cwd: str) -> str:
    extra = [FAST_EXTRA if mode == "fast" else THINK_EXTRA]
    if is_termux():
        extra.append(TERMUX_EXTRA)
    return SYSTEM % (env_info(cwd), "\n".join(extra))


@dataclass
class Reply:
    say: str = ""
    commands: List[str] = field(default_factory=list)
    plan: List[str] = field(default_factory=list)
    done: bool = True

    def canonical(self) -> str:
        d = {"say": self.say, "commands": self.commands, "done": self.done}
        if self.plan:
            d["plan"] = self.plan
        return json.dumps(d, ensure_ascii=False)


def _extract_json(text: str) -> Optional[dict]:
    t = _FENCE.sub("", text.strip()).strip()
    dec = json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(t[i:])
        except ValueError:
            continue
        if isinstance(obj, dict) and ({"say", "commands", "plan", "done"} & set(obj)):
            return obj
    return None


def _str_list(v) -> List[str]:
    if isinstance(v, str):
        v = [v]
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, dict):
            x = x.get("cmd") or x.get("command") or ""
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def parse_reply(text: str) -> Reply:
    t = _THINK.sub("", text or "").strip()
    obj = _extract_json(t)
    if obj is None:
        return Reply(say=t, done=True)
    cmds, plan = _str_list(obj.get("commands")), _str_list(obj.get("plan"))
    done = obj.get("done")
    return Reply(say=str(obj.get("say") or "").strip(), commands=cmds, plan=plan,
                 done=bool(done) if done is not None else not cmds)


def interpret_yes_no(text: str, ask_ai: Optional[Callable[[str], Optional[bool]]] = None) -> bool:
    words = re.sub(r"[!.,?¿¡\"'`]", " ", text.lower()).split()
    if not words:
        return False
    if words[0] in NO:
        return False
    if all(w in YES for w in words):
        return True
    if ask_ai:
        try:
            return bool(ask_ai(text))
        except Exception:
            return False
    return False


def describe_error(e: ProviderError) -> str:
    if e.kind == "auth":
        return "Key rejected: %s Use /key to set a new one." % e.message
    if e.kind == "rate":
        return "Rate limit hit: %s Wait a bit and try again." % e.message
    if e.kind == "network":
        return e.message + " Check your connection."
    return e.message


class Agent:
    def __init__(self, cfg: dict, io, chat_fn=providers.chat, run_fn=shell.run):
        self.cfg, self.io = cfg, io
        self.chat_fn, self.run_fn = chat_fn, run_fn
        self.history: List[dict] = []
        self.cwd = os.getcwd()
        self.timeout = float(os.environ.get("DAT_CMD_TIMEOUT", "300"))

    def reset(self) -> None:
        self.history.clear()

    def _chat(self, system: str, messages: List[dict]) -> str:
        def waiting(sec: int, err: ProviderError) -> None:
            self.io.say("dim", "%s Retrying in %ds..." % (err.message[:60], sec))
        return self.chat_fn(self.cfg["provider"], self.cfg["api_key"], self.cfg["model"], system,
                            messages, cancel=self.io.cancelled, on_wait=waiting)

    def _window(self) -> List[dict]:
        msgs = self.history[-20:]
        while msgs and msgs[0]["role"] != "user":
            msgs = msgs[1:]
        return msgs

    def _ai_yes_no(self, text: str) -> Optional[bool]:
        out = self.chat_fn(
            self.cfg["provider"], self.cfg["api_key"], self.cfg["model"],
            "You classify a reply. Answer with exactly one word: YES, NO or UNCLEAR.",
            [{"role": "user", "content": 'The assistant asked the user to confirm an action. '
                                         'The user replied: "%s"' % text[:200]}], timeout=30)
        return _THINK.sub("", out).strip().upper().startswith("YES")

    def confirm(self, question: str) -> bool:
        self.io.say("warn", question + "\n(yes/no, any language)")
        self.io.status("")
        ans = self.io.ask("answer (yes/no)")
        if ans is None:
            return False
        return interpret_yes_no(ans, self._ai_yes_no)

    def handle(self, text: str) -> None:
        mode = self.cfg.get("mode", "fast")
        max_steps = 8 if mode == "fast" else 14
        self.history.append({"role": "user", "content": text})
        for _ in range(max_steps):
            if self.io.cancelled():
                self.io.say("dim", "Cancelled.")
                return
            self.io.status("thinking")
            try:
                raw = self._chat(build_system(mode, self.cwd), self._window())
            except ProviderError as e:
                self.io.say("err", describe_error(e))
                if self.history and self.history[-1]["role"] == "user":
                    self.history.pop()
                return
            reply = parse_reply(raw)
            if not (reply.say or reply.commands or reply.plan):
                self.io.say("warn", "Empty reply from the model. Try again or switch with /model.")
                return
            self.history.append({"role": "assistant", "content": reply.canonical()})
            if reply.say:
                self.io.say("say", reply.say)
            if reply.plan and not reply.commands:
                self.io.say("say", "Plan:\n" + "\n".join("%d. %s" % (i, s) for i, s in enumerate(reply.plan, 1)))
                if not self.confirm("Run this plan?"):
                    self.io.say("dim", "Skipped.")
                    self.history.append({"role": "user", "content": "The user declined the plan."})
                    return
                self.history.append({"role": "user", "content": "Plan approved. Execute it."})
                continue
            if not reply.commands:
                return
            results = self._run_commands(reply.commands[:5])
            if results is None:
                return
            self.history.append({"role": "user", "content": "\n\n".join(results)})
            if reply.done:
                return
        self.io.say("warn", "Step limit reached. Say 'continue' to go on.")

    def _run_commands(self, commands: List[str]) -> Optional[List[str]]:
        results = []
        for cmd in commands:
            v = safety.check(cmd, self.cwd)
            self.io.say("cmd", cmd)
            if v.level == "block":
                self.io.say("warn", "Blocked: " + v.reason)
                results.append("$ %s\nBLOCKED by the safety filter (%s). Do not retry; tell the user to run it "
                               "themselves with !cmd if they really want it." % (cmd, v.reason))
                continue
            if v.level == "confirm" and not self.confirm("Destructive: %s. Run it?" % v.reason):
                self.io.say("dim", "Skipped.")
                self.history.append({"role": "user", "content": "The user declined: %s. Stop." % cmd})
                return None
            self.io.status("running: " + cmd.split("\n")[0][:30])
            shown = [0]

            def on_line(line: str) -> None:
                shown[0] += 1
                if shown[0] <= 200:
                    self.io.say("out", line)

            res = self.run_fn(cmd, self.cwd, timeout=self.timeout, on_line=on_line, cancel=self.io.cancelled)
            self.cwd = res.cwd
            if shown[0] > 200:
                self.io.say("dim", "... +%d more lines" % (shown[0] - 200))
            if res.cancelled:
                self.io.say("dim", "Cancelled.")
                self.history.append({"role": "user", "content": "$ %s\nCancelled by the user. Stop." % cmd})
                return None
            if res.timed_out:
                self.io.say("warn", "Timed out after %ds." % self.timeout)
            elif res.code != 0:
                self.io.say("dim", "exit %d" % res.code)
            results.append("$ %s\nexit: %d%s\n%s" % (cmd, res.code, " (timed out)" if res.timed_out else "",
                                                     shell.truncate(res.output) or "(no output)"))
        return results
