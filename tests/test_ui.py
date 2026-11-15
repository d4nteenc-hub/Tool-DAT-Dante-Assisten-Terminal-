import curses
import unittest
from unittest import mock

from dat import theme, ui
from dat.theme import ART, G, PALETTE, width


class FakeScr:
    """Just enough of a curses window to see what gets drawn where."""

    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.cells = {}
        self.pos = (0, 0)

    def getmaxyx(self):
        return self.rows, self.cols

    def addstr(self, y, x, text, attr=0):
        for i, ch in enumerate(text):
            self.cells[(y, x + i)] = (ch, attr)

    def addch(self, y, x, ch, attr=0):
        self.cells[(y, x)] = (ch, attr)

    def move(self, y, x):
        self.pos = (y, x)

    def clrtoeol(self):
        y, x = self.pos
        for key in [k for k in self.cells if k[0] == y and k[1] >= x]:
            del self.cells[key]

    def erase(self):
        self.cells.clear()

    clear = erase

    def refresh(self):
        pass

    def text(self, y):
        return "".join(self.cells.get((y, x), (" ", 0))[0] for x in range(self.cols))

    def span(self, y):
        xs = [x for (yy, x), (ch, _) in self.cells.items() if yy == y and ch != " "]
        return (min(xs), max(xs)) if xs else None


class UITestCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(ui, "UTF", True)
        p.start()
        self.addCleanup(p.stop)
        self.tui = ui.TUI()
        self.scr = FakeScr(40, 60)
        self.tui.scr = self.scr
        self.tui.fake_cursor = True


class OutputTests(UITestCase):
    def test_short_output_starts_at_the_top_and_cannot_scroll(self):
        self.tui.say("say", "one")
        self.tui.say("say", "two")
        self.tui.scroll = 5
        self.tui._draw_output(5, 12, 60)
        self.assertIn("one", self.scr.text(6))
        self.assertIn("two", self.scr.text(7))
        for y in range(8, 16):
            self.assertEqual(self.scr.text(y)[1:-1].strip(), "")
        self.assertEqual(self.tui.scroll, 0)
        blocks = [k for k, (ch, _) in self.scr.cells.items() if ch == G["block"]]
        self.assertEqual(blocks, [])
        self.assertNotIn("more", self.scr.text(5))

    def test_scrollbar_and_more_label_appear_only_when_it_overflows(self):
        for i in range(40):
            self.tui.say("say", "line %d" % i)
        self.tui._draw_output(5, 12, 60)
        self.assertTrue(any(ch == G["block"] and k[1] == 58 for k, (ch, _) in self.scr.cells.items()))
        self.assertIn("line 39", self.scr.text(15))
        self.tui.scroll = 5
        self.tui._draw_output(5, 12, 60)
        self.assertIn("more", self.scr.text(5))
        self.assertIn("below", self.scr.text(16))


class InputTests(UITestCase):
    def setUp(self):
        super().setUp()
        self.tui.awaiting = "input"
        self.tui.input_row, self.tui.input_tw = 5, 20

    def set_text(self, text, cur, off=0):
        self.tui.buf, self.tui.cur, self.tui.off = list(text), cur, off

    def test_long_text_scrolls_sideways_and_comes_back(self):
        self.set_text("x" * 100, 100)
        self.tui._fit_input(self.tui.buf, 20)
        self.assertGreaterEqual(self.tui.off, 81)
        self.tui.cur = 0
        self.tui._fit_input(self.tui.buf, 20)
        self.assertEqual(self.tui.off, 0)

    def test_view_returns_to_the_start_when_text_gets_short(self):
        self.set_text("short", 5, off=80)
        self.tui._fit_input(self.tui.buf, 20)
        self.assertEqual(self.tui.off, 0)

    def test_overflow_arrows_are_drawn(self):
        self.set_text("x" * 100, 50, off=40)
        self.tui._draw_input(10, 27)
        row = self.scr.text(11)
        self.assertIn(G["left"], row)
        self.assertIn(G["right"], row)

    def test_tap_puts_cursor_after_the_tapped_letter_so_you_can_fix_a_typo(self):
        self.tui.input_tw = 30
        self.set_text("hello wrld", 10)
        self.tui._click(4 + 6, 5)  # tap the "w"
        self.assertEqual(self.tui.cur, 7)
        self.tui._key("o")
        self.assertEqual("".join(self.tui.buf), "hello world")

    def test_tap_past_the_end_goes_to_the_end(self):
        self.tui.input_tw = 30
        self.set_text("abc", 0)
        self.tui._click(4 + 20, 6)
        self.assertEqual(self.tui.cur, 3)

    def test_taps_outside_the_input_are_ignored(self):
        self.set_text("abc", 1)
        self.tui._click(6, 20)
        self.assertEqual(self.tui.cur, 1)
        self.tui.awaiting = None
        self.tui._click(6, 5)
        self.assertEqual(self.tui.cur, 1)

    def test_tapping_the_edge_arrows_scrolls_the_text(self):
        self.set_text("x" * 100, 60, off=40)
        self.tui._click(3, 5)
        self.assertEqual(self.tui.cur, 30)
        self.tui._fit_input(self.tui.buf, 20)
        self.assertEqual(self.tui.off, 30)
        self.set_text("x" * 100, 45, off=40)
        self.tui._click(4 + 20, 5)
        self.assertEqual(self.tui.cur, 70)

    def test_mouse_events_tap_and_wheel(self):
        self.tui.input_tw = 30
        self.set_text("hello wrld", 10)
        with mock.patch.object(ui.curses, "getmouse", return_value=(0, 10, 5, 0, curses.BUTTON1_PRESSED)):
            self.tui._key(curses.KEY_MOUSE)
        self.assertEqual(self.tui.cur, 7)
        wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
        if wheel_up:
            with mock.patch.object(ui.curses, "getmouse", return_value=(0, 1, 1, 0, wheel_up)):
                self.tui._key(curses.KEY_MOUSE)
            self.assertEqual(self.tui.scroll, 3)

    def test_cursor_is_drawn_by_us_with_the_cursor_style(self):
        self.tui.attrs = {"cursor": 777}
        self.set_text("ab", 1)
        self.tui._draw_input(10, 40)
        self.assertEqual(self.scr.cells[(11, 5)], ("b", 777))
        self.set_text("ab", 2)
        self.tui._draw_input(10, 40)
        self.assertEqual(self.scr.cells[(11, 6)], (" ", 777))


class BannerTests(UITestCase):
    def margins(self, y):
        lo, hi = self.scr.span(y)
        return lo, self.scr.cols - 1 - hi

    def test_banner_title_and_animation_line_are_centered(self):
        self.scr = FakeScr(40, 80)
        self.tui.scr = self.scr
        self.tui._draw()
        left, right = self.margins(len(ART) + 1)
        self.assertLessEqual(abs(left - right), 1)
        left, right = self.margins(len(ART))
        self.assertLessEqual(abs(left - right), 1)
        ax = (80 - max(width(a) for a in ART)) // 2
        self.assertEqual(self.scr.span(0)[0], ax + len(ART[0]) - len(ART[0].lstrip()))

    def test_animation_stays_centered_on_every_frame(self):
        self.scr = FakeScr(40, 70)
        self.tui.scr = self.scr
        self.tui._draw()
        for frame in range(25):
            self.tui.anim = frame
            self.tui._draw_line(self.tui.L["line_y"], 70)
            left, right = self.margins(self.tui.L["line_y"])
            self.assertLessEqual(abs(left - right), 1, frame)


class ThemeTests(unittest.TestCase):
    def test_no_cross_anywhere(self):
        crosses = "†‡✝✞✟✠☦☩+"
        self.assertNotIn("cross", G)
        self.assertNotIn("cross", PALETTE)
        if theme.UTF:
            self.assertFalse(any(c in crosses for v in G.values() for c in v))

    def test_theme_is_blue_with_red_only_for_errors(self):
        for name, (_c256, c8, _bold, _dim) in PALETTE.items():
            if name != "err":
                self.assertNotEqual(c8, curses.COLOR_RED, name)
        self.assertEqual(PALETTE["err"][1], curses.COLOR_RED)
        self.assertIn(PALETTE["b1"][1], (curses.COLOR_CYAN, curses.COLOR_BLUE))


if __name__ == "__main__":
    unittest.main()
