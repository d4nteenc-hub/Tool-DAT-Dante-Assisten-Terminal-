"""Turn the AI's markdown-ish text into styled segments for the terminal.

The raw text is never changed: this only decides how a line is *drawn*.
Styles: the caller's base style, "bold", "code" and "dim".

Handled: **bold**, `code`, fenced blocks, # headings, bullets, [links](url) and
![images](url), *italic*, ~~strike~~, > quotes, --- rules, | tables | and <br>.
Anything else is shown as it came. The rules are deliberately cautious so that
globs (*.txt), snake_case and __dunder__ names are left alone.
"""
from __future__ import annotations

import re
from typing import List, Tuple

Seg = Tuple[str, str]

_INLINE = re.compile(
    r"`([^`\n]+)`"                                              # 1 `code`
    r"|\*\*(?=\S)(.+?)(?<=\S)\*\*"                              # 2 **bold**
    r"|~~(?=\S)(.+?)(?<=\S)~~"                                  # 3 ~~strike~~
    r"|(?<![\w*\\])\*(?=[^\W\d_])([^*\n/\\]+?)(?<=[^\s*])\*(?![\w*])"  # 4 *italic*
    r"|!?\[([^\]\n]*)\]\((https?://[^)\s]+)\)"                  # 5,6 [text](url)
)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
_BULLET = re.compile(r"^(\s*)[*+]\s+(?=\S)")
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_BR = re.compile(r"<br\s*/?>", re.I)


def _inline(text: str, style: str) -> List[Seg]:
    out: List[Seg] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], style))
        code, bold, strike, italic, label, url = m.groups()
        if code is not None:
            out.append((code, "code"))
        elif bold is not None:
            out.extend(_inline(bold, "bold"))
        elif strike is not None:
            out.extend(_inline(strike, style))
        elif italic is not None:
            out.extend(_inline(italic, style))
        else:
            out.append(("%s (%s)" % (label, url) if label else url, style))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], style))
    return out


def _is_table_separator(line: str) -> bool:
    return "|" in line and not re.sub(r"[|:\-\s]", "", line)


def _table_row(line: str) -> str:
    cells = line.strip().strip("|").split("|")
    return " | ".join(c.strip() for c in cells)


def render(lines: List[str], base: str) -> List[List[Seg]]:
    """One list of (text, style) segments per output line."""
    rows: List[List[Seg]] = []
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code          # the fence line itself is not shown
            continue
        if in_code:
            rows.append([(line, "code")])
            continue
        line = _BR.sub(" ", line)
        if _RULE.match(line):
            rows.append([("", base)])
            continue
        if _is_table_separator(line):
            continue
        head = _HEADING.match(line)
        if head:
            rows.append(_inline(head.group(1), "bold") or [("", base)])
            continue
        quote = _QUOTE.match(line)
        if quote:
            rows.append([("| ", "dim")] + (_inline(quote.group(1), base) or [("", base)]))
            continue
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            line = _table_row(line)
        line = _BULLET.sub(lambda m: m.group(1) + "- ", line)
        rows.append(_inline(line, base) or [("", base)])
    return rows
