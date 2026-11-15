from __future__ import annotations

import curses
import locale
import re
import unicodedata
from typing import Dict, List, Tuple

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

def _codeset() -> str:
    try:
        return locale.nl_langinfo(locale.CODESET) or ""
    except (AttributeError, ValueError):
        return locale.getpreferredencoding(False) or ""


UTF = "utf" in _codeset().lower()

G: Dict[str, str] = (
    dict(dot="●", prompt="❯", arrow="▸", cross="†", bar="─", up="▲", down="▼", block="█", track="│",
         mask="•", dots="…", sep="·", spin="⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    if UTF else
    dict(dot="*", prompt=">", arrow=">", cross="+", bar="-", up="^", down="v", block="#", track="|",
         mask="*", dots="...", sep="-", spin="|/-\\")
)

ART_UTF = [
    "▓█████▄   ▄▄▄      ▄▄▄█████▓",
    "▒██▀ ██▌ ▒████▄    ▓  ██▒ ▓▒",
    "░██   █▌ ▒██  ▀█▄  ▒ ▓██░ ▒░",
    "░▓█▄   ▌ ░██▄▄▄▄██ ░ ▓██▓ ░ ",
    "░▒████▓   ▓█   ▓██▒  ▒██▒ ░ ",
    " ▒▒▓  ▒   ▒▒   ▓▒█░  ▒ ░░   ",
    " ░ ▒  ▒    ▒   ▒▒ ░    ░    ",
    " ░ ░  ░    ░   ▒     ░      ",
    "   ░           ░  ░         ",
    " ░                          ",
]
ART_ASCII = [
    " ____    _  _____ ",
    "|  _ \\  / \\|_   _|",
    "| | | |/ _ \\ | |  ",
    "| |_| / ___ \\| |  ",
    "|____/_/   \\_\\_|  ",
]
ART = ART_UTF if UTF else ART_ASCII

MODES = {"fast": ("Fast", "quick replies, acts now"), "think": ("Think", "plans first, then acts")}
HELP = [("/fast", "quick replies"), ("/think", "plan first"), ("/model", "switch model"),
        ("/key", "API key"), ("/help", "all commands"), ("/exit", "quit"), ("!cmd", "run shell directly")]
COMMANDS = ["/fast", "/think", "/model", "/key", "/clear", "/help", "/exit"]

R, Y, W = curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_WHITE
PALETTE = {
    "plain": (255, W, 0, 0), "prompt": (203, R, 1, 0), "say": (210, R, 0, 0), "cmd": (217, W, 0, 0),
    "out": (244, W, 0, 1), "dim": (245, W, 0, 1), "warn": (221, Y, 0, 0), "err": (196, R, 1, 0),
    "b1": (160, R, 1, 0), "b2": (124, R, 0, 0), "b3": (88, R, 0, 1),
    "border": (88, R, 0, 0), "borderon": (160, R, 1, 0), "label": (203, R, 0, 0), "hc": (203, R, 0, 0),
    "ln0": (52, R, 0, 1), "ln1": (88, R, 0, 0), "ln2": (124, R, 0, 0), "ln3": (160, R, 0, 0),
    "head": (196, R, 1, 0), "cross": (196, R, 1, 0), "flash": (224, W, 1, 0), "mode": (196, R, 1, 0),
    "thumb": (160, R, 0, 0), "track": (52, R, 0, 1),
}

Seg = Tuple[str, str]
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean(s: str) -> str:
    return _CTRL.sub("", s.replace("\t", "    "))


def cw(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(s) -> int:
    return sum(cw(c) for c in s)


_TOKENS = re.compile(r"\s+|\S+")


def wrap(segs: List[Seg], w: int, indent: int = 0) -> List[List[Seg]]:
    rows: List[List[Seg]] = []
    cur: List[Seg] = []
    used = 0
    blank = True
    pad = indent if 0 < indent < w - 4 else 0

    def put(text: str, style: str) -> None:
        nonlocal used, blank
        if cur and cur[-1][1] == style:
            cur[-1] = (cur[-1][0] + text, style)
        else:
            cur.append((text, style))
        used += width(text)
        blank = blank and text.isspace()

    def newrow() -> None:
        nonlocal cur, used, blank
        rows.append(cur)
        cur, used, blank = [], 0, True
        if pad:
            put(" " * pad, "plain")

    for text, style in segs:
        for tok in _TOKENS.findall(text):
            tw = width(tok)
            if used + tw <= w:
                put(tok, style)
            elif tok.isspace():
                newrow()
            elif tw <= w - pad:
                if not blank:
                    newrow()
                put(tok, style)
            else:
                for ch in tok:
                    if used + cw(ch) > w:
                        newrow()
                    put(ch, style)
    rows.append(cur)
    return rows


class Entry:
    __slots__ = ("segs", "indent", "w", "rows")

    def __init__(self, segs: List[Seg], indent: int = 0):
        self.segs, self.indent, self.w, self.rows = segs, indent, 0, []

    def wrapped(self, w: int) -> List[List[Seg]]:
        if self.w != w:
            self.rows, self.w = wrap(self.segs, w, self.indent), w
        return self.rows


def kinds() -> Dict[str, Tuple[str, str, str, str]]:
    a = G["arrow"]
    return {
        "say": (" %s " % a, "   ", "say", "say"),
        "cmd": (" $ ", "   ", "cmd", "cmd"),
        "out": ("   ", "   ", "dim", "out"),
        "warn": (" [!] ", "     ", "warn", "warn"),
        "err": (" [x] ", "     ", "err", "err"),
        "dim": (" ", " ", "dim", "dim"),
        "plain": ("", "", "plain", "plain"),
        "title": ("", "", "head", "head"),
    }
