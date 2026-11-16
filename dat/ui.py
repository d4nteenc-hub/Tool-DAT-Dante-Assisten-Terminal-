from __future__ import annotations

import curses
import os
import queue
import threading
import time
import traceback
from typing import Callable, Dict, List, Optional

from . import __version__
from . import richtext
from .theme import (ART, COMMANDS, G, HELP, MODES, PALETTE, UTF, Entry, clean, cw, kinds, width)

MAX_LOG = 3000


class TUI:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.log: List[Entry] = []
        self.inbox: "queue.Queue[Optional[str]]" = queue.Queue()
        self.cancel_ev = threading.Event()
        self.done = threading.Event()
        self.awaiting: Optional[str] = None
        self.secret = False
        self.buf: List[str] = []
        self.cur = self.off = 0
        self.hist: List[str] = []
        self.hidx = 0
        self.draft = ""
        self.scroll = 0
        self.last_total = 0
        self.mode = "fast"
        self.model_line = ""
        self.cwd = ""
        self.status_text = ""
        self.dirty = True
        self.anim = 0
        self.last_anim = 0.0
        self.animate = not os.environ.get("DAT_NO_ANIM")
        self.error: Optional[str] = None
        self.scr = None
        self.attrs: Dict[str, int] = {}
        self.L: Optional[dict] = None
        self.cursor_pos = None
        self.cursor_state = None
        self.fake_cursor = False
        self.mouse = False
        self.mouse_applied = False
        self.input_row = -1
        self.input_tw = 0

    def say(self, kind: str, text: str) -> None:
        first, cont, pstyle, tstyle = kinds().get(kind, kinds()["plain"])
        lines = clean(str(text)).split("\n")
        rows = None
        if kind == "say":
            try:  # a formatting problem must never cost the user the message
                rows = richtext.render(lines, tstyle) or None
            except Exception:
                rows = None
        if rows is None:
            rows = [[(line, tstyle)] for line in lines]
        with self.lock:
            for i, segs in enumerate(rows):
                prefix = first if i == 0 else cont
                self.log.append(Entry([(prefix, pstyle)] + segs, width(prefix)))
            if len(self.log) > MAX_LOG:
                del self.log[:MAX_LOG // 5]
            self.dirty = True

    def set_mode(self, mode: str) -> None:
        self.mode, self.dirty = mode, True

    def set_model(self, provider: str, model: str) -> None:
        line = "%s %s %s" % (provider, G["sep"], model) if provider and model else ""
        self.model_line, self.dirty = line, True

    def set_cwd(self, path: str) -> None:
        self.cwd, self.dirty = path, True

    def status(self, text: str) -> None:
        self.status_text, self.dirty = text, True

    def cancelled(self) -> bool:
        return self.cancel_ev.is_set()

    def clear(self) -> None:
        with self.lock:
            self.log.clear()
            self.scroll = self.last_total = 0
            self.dirty = True

    def ask(self, label: str = "input", secret: bool = False) -> Optional[str]:
        self.cancel_ev.clear()
        with self.lock:
            self.awaiting, self.secret, self.status_text, self.dirty = label, secret, "", True
        while True:
            try:
                return self.inbox.get(timeout=0.5)
            except queue.Empty:
                if self.done.is_set():
                    return None

    read_line = ask

    def run(self, controller: Callable[["TUI"], None]) -> Optional[str]:
        os.environ.setdefault("ESCDELAY", "25")

        def target() -> None:
            try:
                controller(self)
            except BaseException:
                self.error = traceback.format_exc()
            finally:
                self.done.set()

        curses.wrapper(self._main, target)
        return self.error

    def _main(self, scr, target) -> None:
        self.scr = scr
        scr.keypad(True)
        scr.timeout(90)
        self._init_colors()
        self._init_input()
        threading.Thread(target=target, daemon=True).start()
        while not self.done.is_set():
            try:
                try:
                    ch = scr.get_wch()
                except curses.error:
                    ch = None
                if ch is not None:
                    self._key(ch)
                self._tick()
            except KeyboardInterrupt:
                self._cancel(hint=True)

    def _init_input(self) -> None:
        # Draw our own cursor: the terminal's cursor flashes as a white block whenever the
        # animation row is repainted, so keep the real one hidden.
        try:
            curses.curs_set(0)
            self.fake_cursor = True
        except curses.error:
            self.fake_cursor = False

    def set_mouse(self, on: bool) -> None:
        # Mouse reporting makes Termux send taps to DAT instead of opening the keyboard,
        # so the app only turns it on by default outside Termux (see cli.mouse_on).
        self.mouse, self.dirty = bool(on), True

    def _apply_mouse(self) -> None:
        self.mouse_applied = self.mouse
        try:
            if self.mouse:
                curses.mouseinterval(0)
                curses.mousemask(curses.ALL_MOUSE_EVENTS)
            else:
                curses.mousemask(0)
        except (curses.error, AttributeError):
            pass

    def _init_colors(self) -> None:
        wide = False
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
                bg = -1
            except curses.error:
                bg = curses.COLOR_BLACK
            wide = curses.COLORS >= 256
            for i, (name, (c256, c8, bold, dim)) in enumerate(PALETTE.items(), 1):
                curses.init_pair(i, c256 if wide else c8, bg)
                a = curses.color_pair(i) | (curses.A_BOLD if bold else 0)
                self.attrs[name] = a | (curses.A_DIM if dim and not wide else 0)
        else:
            for name, (_, _, bold, dim) in PALETTE.items():
                self.attrs[name] = (curses.A_BOLD if bold else 0) | (curses.A_DIM if dim else 0)
        self.attrs["cursor"] = self.attrs.get("cursor", 0) | curses.A_REVERSE

    def _key(self, ch) -> None:
        if isinstance(ch, int):
            k = ch
            if k == curses.KEY_RESIZE:
                self.scr.clear()
            elif k == curses.KEY_MOUSE:
                self._mouse()
            elif k == curses.KEY_UP:
                self.scroll += 2
            elif k == curses.KEY_DOWN:
                self.scroll = max(0, self.scroll - 2)
            elif k == curses.KEY_PPAGE:
                self.scroll += max(1, (self.L or {}).get("out_h", 10) - 3)
            elif k == curses.KEY_NPAGE:
                self.scroll = max(0, self.scroll - max(1, (self.L or {}).get("out_h", 10) - 3))
            elif k == curses.KEY_HOME:
                self.scroll = 10 ** 9
            elif k == curses.KEY_END:
                self.scroll = 0
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                self._backspace()
            elif k == curses.KEY_DC and self.cur < len(self.buf):
                del self.buf[self.cur]
            elif k == curses.KEY_LEFT:
                self.cur = max(0, self.cur - 1)
            elif k == curses.KEY_RIGHT:
                self.cur = min(len(self.buf), self.cur + 1)
            elif k in (curses.KEY_ENTER, 10, 13):
                self._submit()
            self.dirty = True
            return
        if ch in ("\n", "\r"):
            self._submit()
        elif ch in ("\x7f", "\b"):
            self._backspace()
        elif ch == "\x1b":
            self._cancel()
        elif ch == "\x04":
            if not self.buf and self.awaiting is not None:
                with self.lock:
                    self.awaiting = None
                self.inbox.put(None)
        elif ch == "\x01":
            self.cur = 0
        elif ch == "\x05":
            self.cur = len(self.buf)
        elif ch == "\x15":
            del self.buf[:self.cur]
            self.cur = 0
        elif ch == "\x0b":
            del self.buf[self.cur:]
        elif ch == "\x17":
            i = self.cur
            while i > 0 and self.buf[i - 1] == " ":
                i -= 1
            while i > 0 and self.buf[i - 1] != " ":
                i -= 1
            del self.buf[i:self.cur]
            self.cur = i
        elif ch == "\x0c":
            self.scr.clear()
        elif ch == "\x10":
            self._history(-1)
        elif ch == "\x0e":
            self._history(1)
        elif ch == "\t":
            self._complete()
        elif ch.isprintable():
            self.buf.insert(self.cur, ch)
            self.cur += 1
        self.dirty = True

    def _mouse(self) -> None:
        try:
            _id, mx, my, _z, bstate = curses.getmouse()
        except curses.error:
            return
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self.scroll += 3
        elif bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self.scroll = max(0, self.scroll - 3)
        elif bstate & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED):
            self._click(mx, my)

    def _click(self, mx: int, my: int) -> None:
        """Tap in the input box: put the cursor right after the tapped character, so Backspace
        removes it. Tapping the edge arrows scrolls the text sideways."""
        if self.awaiting is None or self.input_row < 0 or abs(my - self.input_row) > 1:
            return
        tw, n = self.input_tw, len(self.buf)
        disp = [G["mask"]] * n if self.secret else self.buf
        step = max(1, tw // 2)
        if mx < 4:
            self.cur = max(0, self.off - step) if self.off > 0 else 0
        elif mx >= 4 + tw:
            if width(disp[self.off:]) > tw:
                seen, end = 0, self.off
                while end < n and seen + cw(disp[end]) <= tw:
                    seen += cw(disp[end])
                    end += 1
                self.cur = min(n, end + step)
            else:
                self.cur = n
        else:
            col, acc, idx = mx - 4, 0, n
            for j in range(self.off, n):
                w = cw(disp[j])
                if col < acc + w:
                    idx = j + 1
                    break
                acc += w
            self.cur = idx
        self.dirty = True

    def _fit_input(self, disp: List[str], tw: int) -> None:
        cur = min(self.cur, len(disp))
        self.off = max(0, min(self.off, cur))
        while width(disp[self.off:cur]) > tw - 1:
            self.off += 1
        while self.off > 0 and width(disp[self.off - 1:]) <= tw - 1:
            self.off -= 1

    @staticmethod
    def _center(text: str, cols: int) -> int:
        return max(0, (cols - width(text)) // 2)

    def _backspace(self) -> None:
        if self.cur > 0:
            del self.buf[self.cur - 1]
            self.cur -= 1

    def _history(self, d: int) -> None:
        if not self.hist:
            return
        if self.hidx == len(self.hist):
            self.draft = "".join(self.buf)
        self.hidx = max(0, min(len(self.hist), self.hidx + d))
        text = self.hist[self.hidx] if self.hidx < len(self.hist) else self.draft
        self.buf, self.cur = list(text), len(text)

    def _complete(self) -> None:
        t = "".join(self.buf)
        if t.startswith("/") and " " not in t:
            m = [c for c in COMMANDS if c.startswith(t)]
            if len(m) == 1:
                self.buf = list(m[0] + " ")
                self.cur = len(self.buf)

    def _submit(self) -> None:
        with self.lock:
            label = self.awaiting
            text = "".join(self.buf)
            if label is None or (label == "input" and not text.strip()):
                return
            secret = self.secret
            self.awaiting = None
            self.buf, self.cur, self.off, self.scroll = [], 0, 0, 0
            self.dirty = True
        if label == "input":
            if not self.hist or self.hist[-1] != text:
                self.hist.append(text)
            self.hidx = len(self.hist)
        if text:
            shown = G["mask"] * min(len(text), 24) if secret else text
            with self.lock:
                self.log.append(Entry([("dat %s" % G["prompt"], "prompt"), (" " + clean(shown), "plain")], 6))
        self.inbox.put(text)

    def _cancel(self, hint: bool = False) -> None:
        with self.lock:
            if self.awaiting is None:
                self.cancel_ev.set()
                self.status_text = "cancelling" + G["dots"]
            elif self.awaiting != "input":
                self.awaiting = None
                self.inbox.put("")
            elif self.buf:
                self.buf, self.cur, self.off = [], 0, 0
            elif hint:
                self.say("dim", "Press Ctrl+D or type /exit to quit.")
            self.dirty = True

    def _tick(self) -> None:
        if self.mouse != self.mouse_applied:
            self._apply_mouse()
        now = time.time()
        moved = now - self.last_anim >= 0.09
        if moved:
            self.last_anim, self.anim = now, self.anim + 1
        if self.dirty:
            self.dirty = False
            self._draw()
        elif moved and self.L and (self.animate or self.awaiting is None):
            self._draw_anim()

    def _layout(self, rows: int, cols: int) -> Optional[dict]:
        if cols < 24:
            return None
        aw = max(len(x) for x in ART)
        help_h = 4 if (rows >= 24 and cols >= 44) else 1
        for kind, bh in (("full", len(ART) + 3), ("compact", 2), ("mini", 1)):
            if kind == "full" and cols < aw + 2:
                continue
            out_h = rows - bh - 1 - 3 - help_h
            if out_h >= (8 if kind == "full" else 5):
                return dict(kind=kind, bh=bh, out_h=out_h, help_h=help_h)
        out_h = rows - 1 - 1 - 3 - 1
        return dict(kind="mini", bh=1, out_h=out_h, help_h=1) if out_h >= 3 else None

    def _put(self, y: int, x: int, text: str, style: str, limit: Optional[int] = None) -> int:
        rows, cols = self.scr.getmaxyx()
        if y < 0 or y >= rows:
            return x
        maxx = cols if limit is None else min(cols, limit)
        x0, out = x, []
        for ch in text:
            w = cw(ch)
            if x + w > maxx:
                break
            out.append(ch)
            x += w
        if out:
            try:
                self.scr.addstr(y, x0, "".join(out), self.attrs.get(style, 0))
            except curses.error:
                pass
        return x

    def _clear_row(self, y: int) -> None:
        try:
            self.scr.move(y, 0)
            self.scr.clrtoeol()
        except curses.error:
            pass

    def _box(self, y: int, x: int, h: int, w: int, style: str) -> None:
        s, a = self.scr, self.attrs.get(style, 0)
        hl, vl, ul, ur, ll, lr = ("─", "│", "┌", "┐", "└", "┘") if UTF else (
            curses.ACS_HLINE, curses.ACS_VLINE, curses.ACS_ULCORNER, curses.ACS_URCORNER,
            curses.ACS_LLCORNER, curses.ACS_LRCORNER)

        def ch(yy: int, xx: int, c) -> None:
            try:
                s.addstr(yy, xx, c, a) if isinstance(c, str) else s.addch(yy, xx, c, a)
            except curses.error:
                pass

        for i in range(1, w - 1):
            ch(y, x + i, hl)
            ch(y + h - 1, x + i, hl)
        for j in range(1, h - 1):
            ch(y + j, x, vl)
            ch(y + j, x + w - 1, vl)
        ch(y, x, ul)
        ch(y, x + w - 1, ur)
        ch(y + h - 1, x, ll)
        ch(y + h - 1, x + w - 1, lr)

    def _draw(self) -> None:
        s = self.scr
        s.erase()
        rows, cols = s.getmaxyx()
        L = self._layout(rows, cols)
        self.L = L
        if L is None:
            self._put(0, 0, "Terminal too small", "warn")
            self._finish()
            return
        bh = L["bh"]
        sub = "v%s" % __version__ + ((" %s %s" % (G["sep"], self.model_line)) if self.model_line else "")
        if L["kind"] == "full":
            ax = self._center(max(ART, key=width), cols)
            for i, art in enumerate(ART):
                self._put(i, ax, art, "b1" if i < 5 else "b2" if i < 8 else "b3")
            title = "Dante Assistant Terminal"
            self._put(len(ART) + 1, self._center(title, cols), title, "say")
            self._put(len(ART) + 2, self._center(sub, cols), sub, "dim")
            L["line_y"] = len(ART)
        elif L["kind"] == "compact":
            text = "Dante Assistant Terminal  " + sub
            self._put(1, self._center(text, cols), text, "say", limit=cols - 1)
            L["line_y"] = 0
        else:
            L["line_y"] = 0
        self._draw_line(L["line_y"], cols)
        self._draw_mode(bh, cols)
        y0 = bh + 1
        self._draw_output(y0, L["out_h"], cols)
        self._draw_input(y0 + L["out_h"], cols)
        self._draw_help(y0 + L["out_h"] + 3, L["help_h"], cols)
        self._finish()

    def _draw_anim(self) -> None:
        cols = self.scr.getmaxyx()[1]
        if self.animate:
            self._draw_line(self.L["line_y"], cols)
        self._draw_mode(self.L["bh"], cols)
        self._finish()

    def _finish(self) -> None:
        if self.fake_cursor:
            self.scr.refresh()
            return
        vis = 1 if self.awaiting is not None and self.cursor_pos else 0
        if vis != self.cursor_state:
            try:
                curses.curs_set(vis)
            except curses.error:
                pass
            self.cursor_state = vis
        if vis:
            try:
                self.scr.move(*self.cursor_pos)
            except curses.error:
                pass
        self.scr.refresh()

    def _draw_line(self, y: int, cols: int) -> None:
        n = max(3, min(11, (cols - 8) // 2))
        t = self.anim % (n + 8) if self.animate else n + 7
        head = t if t < n else -1
        flash = n <= t < n + 3
        self._clear_row(y)

        def style(i: int) -> str:
            d = head - i
            return "head" if head >= 0 and d == 0 else "ln3" if head >= 0 and d == 1 else \
                "ln2" if head >= 0 and d == 2 else "ln1" if head >= 0 and d == 3 else "ln0"

        x = self._center(G["bar"] * (2 * n) + "   ", cols)
        for i in range(n):
            x = self._put(y, x, G["bar"], style(i))
        x = self._put(y, x, " %s " % G["gem"], "flash" if flash else "gem")
        for i in range(n - 1, -1, -1):
            x = self._put(y, x, G["bar"], style(i))

    def _draw_mode(self, y: int, cols: int) -> None:
        self._clear_row(y)
        name, desc = MODES[self.mode]
        x = self._put(y, 1, "%s %s" % (G["dot"], name), "mode")
        if self.awaiting is None:
            frames = G["spin"]
            right, rstyle = "%s %s" % (frames[self.anim % len(frames)], self.status_text or "working"), "say"
        else:
            home = os.path.expanduser("~")
            right = self.cwd.replace(home, "~", 1) if self.cwd.startswith(home) else self.cwd
            rstyle = "dim"
        desc_txt = " %s %s" % (G["sep"], desc)
        if rstyle == "dim":
            room = cols - x - width(desc_txt) - 3
            right = (G["dots"] + right[-(room - 1):]) if 1 < room < width(right) else right if room >= width(right) else ""
        rw = width(right)
        self._put(y, x, desc_txt, "dim", limit=cols - rw - 3)
        if right:
            self._put(y, cols - rw - 1, right, rstyle)

    def _draw_output(self, y0: int, h: int, cols: int) -> None:
        self._box(y0, 0, h, cols, "border")
        self._put(y0, 2, " output ", "label")
        vis, w = h - 2, cols - 5
        with self.lock:
            entries = list(self.log)
        rows = []
        for e in entries:
            rows.extend(e.wrapped(w))
        total = len(rows)
        if self.scroll > 0 and self.last_total and total > self.last_total:
            self.scroll += total - self.last_total
        self.last_total = total
        self.scroll = max(0, min(self.scroll, max(0, total - vis)))
        end = total - self.scroll
        start = max(0, end - vis)
        chunk = rows[start:end]
        top = y0 + 1
        for i, segs in enumerate(chunk):
            x = 2
            for text, style in segs:
                x = self._put(top + i, x, text, style, limit=2 + w)
        if start > 0:
            lab = " %s %d more " % (G["up"], start)
            self._put(y0, cols - width(lab) - 3, lab, "dim")
        if self.scroll > 0:
            lab = " %s %d below %s End " % (G["down"], self.scroll, G["sep"])
            self._put(y0 + h - 1, cols - width(lab) - 3, lab, "dim")
        if total > vis:
            thumb = max(1, vis * vis // total)
            max_scroll = total - vis
            pos = (max_scroll - self.scroll) * (vis - thumb) // max_scroll
            for i in range(vis):
                on = pos <= i < pos + thumb
                self._put(y0 + 1 + i, cols - 2, G["block"] if on else G["track"], "thumb" if on else "track")

    def _draw_input(self, y0: int, cols: int) -> None:
        active = self.awaiting is not None
        self._box(y0, 0, 3, cols, "borderon" if active else "border")
        self._put(y0, 2, " %s " % (self.awaiting if active else "busy %s Esc cancels" % G["sep"]),
                  "label" if active else "dim")
        row = y0 + 1
        self._put(row, 2, G["prompt"], "prompt")
        tw = cols - 7
        disp = [G["mask"]] * len(self.buf) if self.secret else self.buf
        self._fit_input(disp, tw)
        self.input_row, self.input_tw = row, tw
        hint = "ask anything, or !cmd for shell"
        placeholder = not self.buf and self.awaiting == "input"
        if placeholder:
            self._put(row, 4, hint, "dim", limit=4 + tw)
        self._put(row, 4, "".join(disp[self.off:]), "plain", limit=4 + tw)
        if self.off > 0:
            self._put(row, 3, G["left"], "label")
        if width(disp[self.off:]) > tw:
            self._put(row, 4 + tw, G["right"], "label")
        cx = 4 + width(disp[self.off:self.cur])
        self.cursor_pos = (row, cx)
        if active and self.fake_cursor:
            under = hint[0] if placeholder else (disp[self.cur] if self.cur < len(disp) else " ")
            self._put(row, cx, under, "cursor", limit=cols - 1)

    def _draw_help(self, y: int, h: int, cols: int) -> None:
        if h <= 1:
            self._put(y, 1, "  ".join(c for c, _ in HELP), "dim", limit=cols - 1)
            return
        colw = (cols - 2) // 2
        for i, (cmd, desc) in enumerate(HELP):
            r, c = divmod(i, 2)
            x = 1 + c * colw
            last_alone = i == len(HELP) - 1 and c == 0
            self._put(y + r, x, cmd.ljust(7), "hc", limit=x + colw)
            self._put(y + r, x + 7, desc, "dim", limit=cols - 1 if last_alone else x + colw - 1)
