from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import __version__, config, providers, shell, updater
from .agent import Agent, describe_error, is_termux
from .providers import ORDER, PROVIDERS, ProviderError

MODE_TEXT = {"fast": "Fast - quick replies, acts now", "think": "Think - plans first, then acts"}

HELP_TEXT = [
    ("title", "Commands"),
    ("plain", "  /fast    quick replies, acts now"),
    ("plain", "  /think   plans first, then acts"),
    ("plain", "  /model   list models; /model <n|name>"),
    ("plain", "  /key     change API key or provider"),
    ("plain", "  /mouse   tap to move the cursor (on/off/auto)"),
    ("plain", "  /update  check for a newer DAT"),
    ("plain", "  /clear   clear screen and AI memory"),
    ("plain", "  /help    this list"),
    ("plain", "  /exit    quit (Ctrl+D works too)"),
    ("plain", "  !cmd     run a shell command directly"),
    ("title", "Keys"),
    ("plain", "  Up/Down      scroll the output"),
    ("plain", "  PgUp/PgDn    scroll a page"),
    ("plain", "  Home/End     top / bottom"),
    ("plain", "  Tab          complete a /command"),
    ("plain", "  Ctrl+P/N     input history"),
    ("plain", "  Esc          cancel the running task"),
    ("dim", "Destructive commands ask first. Answer yes or no in any language."),
]


def mouse_on(cfg: dict) -> bool:
    """Tap support is on for desktop terminals and off in Termux, unless the user chose."""
    m = cfg.get("mouse", "auto")
    return m == "on" or (m == "auto" and not is_termux())


def short_path(p: str) -> str:
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def clean_key(s: str) -> str:
    k = s.strip().strip("\"'")
    if k.lower().startswith("bearer "):
        k = k[7:]
    return "".join(k.split())


def pick_provider(ui) -> Optional[str]:
    ui.say("say", "Unknown key format. Pick your provider:\n" +
           "\n".join("%d) %s" % (i, PROVIDERS[p].name) for i, p in enumerate(ORDER, 1)))
    while True:
        a = ui.ask("provider (1-%d)" % len(ORDER))
        if a is None:
            return None
        a = a.strip()
        if not a:
            return ""
        if a.isdigit() and 1 <= int(a) <= len(ORDER):
            return ORDER[int(a) - 1]
        ui.say("warn", "Pick a number from 1 to %d." % len(ORDER))


def setup(ui, cfg: dict, first: bool) -> Optional[dict]:
    if first:
        ui.say("title", "Welcome. Let's connect an AI.")
        ui.say("dim", "Works with Groq, Gemini, OpenRouter, OpenAI and Anthropic.\n"
                      "Your key is stored only on this device.\n"
                      "Free keys:\n  console.groq.com/keys\n  aistudio.google.com/apikey")
    else:
        ui.say("title", "Change API key")
    ui.say("plain", "Paste your API key below." + ("" if first else " Empty = cancel."))
    while True:
        key = ui.ask("api key (hidden)", secret=True)
        if key is None:
            return None
        key = clean_key(key)
        if not key:
            if not first:
                ui.say("dim", "Cancelled.")
                return cfg
            ui.say("dim", "Paste your key, or press Ctrl+D to quit.")
            continue
        pid = providers.detect(key)
        guessed = pid is not None
        if not pid:
            pid = pick_provider(ui)
            if pid is None:
                return None
            if pid == "":
                continue
        name = PROVIDERS[pid].name
        ui.say("say", ("Detected: %s" if guessed else "Provider: %s") % name)
        ui.status("testing connection")
        try:
            models = providers.list_models(pid, key)
        except ProviderError as e:
            ui.status("")
            if e.kind in ("auth", "network"):
                ui.say("err", ("%s rejected the key. Check it and paste again." % name) if e.kind == "auth"
                       else e.message + " Check your connection and paste the key again.")
                continue
            ui.say("warn", "Couldn't list models (%s). Using a default." % e.message)
            models = []
        ui.status("")
        model = providers.pick_default(pid, models)
        cfg.update(provider=pid, api_key=key, model=model)
        try:
            ui.say("dim", "Saved to " + short_path(str(config.save(cfg))))
        except OSError as e:
            ui.say("warn", "Couldn't save the key (%s). It works until you quit." % e.strerror)
        ui.say("say", "Connected. Model: " + model)
        return cfg


class App:
    def __init__(self, ui, cfg: dict):
        self.ui, self.cfg = ui, cfg
        self.agent: Optional[Agent] = None
        self.models: List[str] = []

    def header(self) -> None:
        c = self.cfg
        self.ui.set_model(PROVIDERS[c["provider"]].name.lower(), c["model"])

    def save(self) -> None:
        try:
            config.save(self.cfg)
        except OSError:
            pass

    def start(self) -> None:
        ui, cfg = self.ui, self.cfg
        ui.set_mode(cfg["mode"])
        ui.set_mouse(mouse_on(cfg))
        if not config.is_ready(cfg) and setup(ui, cfg, True) is None:
            return
        self.agent = Agent(cfg, ui)
        ui.set_cwd(self.agent.cwd)
        self.header()
        ui.say("dim", "Ready. Tell me what to do, or type /help.")
        self.loop()

    def loop(self) -> None:
        ui = self.ui
        while True:
            line = ui.ask("input")
            if line is None:
                return
            line = line.strip()
            try:
                if line.startswith("/"):
                    if self.command(line) is False:
                        return
                elif line.startswith("!"):
                    self.direct(line[1:].strip())
                elif line:
                    self.agent.handle(line)
            except ProviderError as e:
                ui.say("err", describe_error(e))
            except Exception as e:
                ui.say("err", "Internal error: %s: %s" % (type(e).__name__, e))
            ui.status("")
            ui.set_cwd(self.agent.cwd)

    def command(self, line: str) -> Optional[bool]:
        ui, cfg = self.ui, self.cfg
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        if cmd in ("/exit", "/quit", "/q"):
            return False
        if cmd in ("/fast", "/think"):
            cfg["mode"] = cmd[1:]
            self.save()
            ui.set_mode(cfg["mode"])
            ui.say("dim", "Mode: " + MODE_TEXT[cfg["mode"]])
        elif cmd == "/help":
            for kind, text in HELP_TEXT:
                ui.say(kind, text)
        elif cmd == "/clear":
            ui.clear()
            self.agent.reset()
        elif cmd == "/key":
            if setup(ui, cfg, False) is None:
                return False
            self.header()
        elif cmd == "/model":
            self.model(arg)
        elif cmd == "/update":
            self.update()
        elif cmd == "/mouse":
            self.mouse(arg)
        else:
            ui.say("warn", "Unknown command %s. Try /help." % cmd)
        return None

    def mouse(self, arg: str) -> None:
        ui, cfg = self.ui, self.cfg
        a = arg.strip().lower()
        if a not in ("", "on", "off", "auto"):
            ui.say("warn", "Use /mouse on, /mouse off or /mouse auto.")
            return
        cfg["mouse"] = a or ("off" if mouse_on(cfg) else "on")
        ui.set_mouse(mouse_on(cfg))
        self.save()
        if cfg["mouse"] == "auto":
            ui.say("say", "Tap-to-move is automatic: on in desktop terminals, off in Termux. Right now it is %s."
                   % ("on" if mouse_on(cfg) else "off"))
        elif cfg["mouse"] == "on":
            ui.say("say", "Tap-to-move is on: tap typed text to put the cursor there.")
            ui.say("dim", "If the keyboard stops showing when you tap the input, run /mouse off.")
        else:
            ui.say("say", "Tap-to-move is off. Move with the arrow keys; the keyboard shows normally.")

    def update(self) -> None:
        ui = self.ui
        ui.status("checking for updates")
        try:
            latest = updater.fetch_latest()
        except updater.UpdateError as e:
            ui.say("err", str(e))
            return
        if updater.parse_version(latest) == updater.parse_version(__version__):
            ui.say("say", "You're up to date (v%s)." % __version__)
            return
        if updater.is_newer(latest, __version__):
            question = "DAT v%s is available (you have v%s). Update now?" % (latest, __version__)
        else:
            question = ("GitHub has v%s, which is older than your v%s. Switch to v%s anyway?"
                        % (latest, __version__, latest))
        if not self.agent.confirm(question):
            ui.say("dim", "Okay, not changing anything.")
            return
        ui.status("downloading")
        try:
            method, new = updater.update()
        except updater.UpdateError as e:
            ui.say("err", str(e))
            return
        ui.say("say", "Now on v%s (%s). Restart DAT to use it: /exit, then run dat again." % (new, method))

    def model(self, arg: str) -> None:
        ui, cfg = self.ui, self.cfg
        chosen = ""
        if arg.isdigit():
            n = int(arg)
            if not 1 <= n <= len(self.models):
                ui.say("warn", "No model #%d. Run /model to see the list." % n)
                return
            chosen = self.models[n - 1]
        elif arg and not arg.startswith("list"):
            chosen = arg
        if chosen:
            cfg["model"] = chosen
            self.save()
            self.header()
            ui.say("say", "Model: " + chosen)
            return
        flt = arg[4:].strip().lower()
        ui.status("loading models")
        try:
            found = providers.list_models(cfg["provider"], cfg["api_key"])
        except ProviderError as e:
            ui.say("err", describe_error(e))
            return
        found = [m for m in found if flt in m.lower()]
        if not found:
            ui.say("warn", "No models found.")
            return
        self.models = found[:40]
        rows = ["%2d) %s%s" % (i, m, "  *" if m == cfg["model"] else "") for i, m in enumerate(self.models, 1)]
        more = "\n...and %d more. Narrow it: /model list <text>" % (len(found) - 40) if len(found) > 40 else ""
        ui.say("say", "Models (* = current)\n" + "\n".join(rows) + more)
        ui.say("dim", "Switch: /model <number> or /model <name>")

    def direct(self, cmd: str) -> None:
        ui, agent = self.ui, self.agent
        if not cmd:
            ui.say("dim", "Usage: !<command>, for example !ls")
            return
        ui.say("cmd", cmd)
        ui.status("running")
        count = [0]

        def on_line(line: str) -> None:
            count[0] += 1
            if count[0] <= 300:
                ui.say("out", line)

        res = shell.run(cmd, agent.cwd, timeout=agent.timeout, on_line=on_line, cancel=ui.cancelled)
        agent.cwd = res.cwd
        if count[0] > 300:
            ui.say("dim", "... +%d more lines" % (count[0] - 300))
        if res.cancelled:
            ui.say("dim", "Cancelled.")
        elif res.timed_out:
            ui.say("warn", "Timed out.")
        elif res.code:
            ui.say("dim", "exit %d" % res.code)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="dat", description="DAT - Dante Assistant Terminal")
    ap.add_argument("--version", action="version", version="dat %s" % __version__)
    ap.add_argument("--config", action="store_true", help="print the config file path and exit")
    ap.add_argument("--reset", action="store_true", help="delete the saved API key and settings")
    args = ap.parse_args(argv)
    if args.config:
        print(config.config_path())
        return 0
    if args.reset:
        print("Config deleted." if config.reset() else "Nothing to delete.")
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("DAT needs an interactive terminal.", file=sys.stderr)
        return 1
    try:
        from .ui import TUI
    except ImportError:
        print("This Python has no curses module. On Windows use WSL, or run `pip install windows-curses`.",
              file=sys.stderr)
        return 1
    cfg = config.load()
    err = TUI().run(lambda tui: App(tui, cfg).start())
    if err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
