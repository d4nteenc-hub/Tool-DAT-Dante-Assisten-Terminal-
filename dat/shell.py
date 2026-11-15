from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
_MARK = "__DAT_CWD__"
MAX_AI_CHARS = 2500


@dataclass
class Result:
    code: int
    output: str
    cwd: str
    timed_out: bool = False
    cancelled: bool = False


def shell_path() -> str:
    return shutil.which("bash") or shutil.which("sh") or "/bin/sh"


def truncate(text: str, limit: int = MAX_AI_CHARS) -> str:
    if len(text) <= limit:
        return text
    head, tail = int(limit * 0.4), int(limit * 0.55)
    return "%s\n... [%d chars omitted] ...\n%s" % (text[:head], len(text) - head - tail, text[-tail:])


def _kill(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            continue


def run(cmd: str, cwd: str, *, timeout: float = 300, on_line: Optional[Callable[[str], None]] = None,
        cancel: Optional[Callable[[], bool]] = None) -> Result:
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")
    wrapped = "trap 'printf \"\\n%s%%s\\n\" \"$(pwd)\"' EXIT\n%s\n" % (_MARK, cmd)
    env = dict(os.environ, PAGER="cat", GIT_PAGER="cat", GIT_TERMINAL_PROMPT="0",
               DEBIAN_FRONTEND="noninteractive", PYTHONUNBUFFERED="1", NO_COLOR="1")
    proc = subprocess.Popen([shell_path(), "-c", wrapped], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    lines: List[str] = []
    blanks = [0]
    new_cwd = [cwd]

    def emit(raw: bytes) -> None:
        text = raw.decode("utf-8", "replace")
        parts = [p for p in text.split("\r") if p]
        line = _ANSI.sub("", parts[-1] if parts else "").rstrip()
        if line.startswith(_MARK):
            new_cwd[0] = line[len(_MARK):] or cwd
            return
        if not line:
            blanks[0] += 1
            return
        for _ in range(blanks[0]):
            lines.append("")
            if on_line:
                on_line("")
        blanks[0] = 0
        lines.append(line)
        if on_line:
            on_line(line)

    def reader() -> None:
        buf = b""
        try:
            for chunk in iter(lambda: proc.stdout.read1(4096), b""):
                buf += chunk
                while b"\n" in buf:
                    one, buf = buf.split(b"\n", 1)
                    emit(one)
            if buf:
                emit(buf)
        except (ValueError, OSError):
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    start = time.time()
    timed_out = cancelled = False
    while proc.poll() is None:
        if cancel and cancel():
            cancelled = True
        elif time.time() - start > timeout:
            timed_out = True
        if cancelled or timed_out:
            _kill(proc)
            break
        time.sleep(0.05)
    t.join(1.5)
    if not t.is_alive():
        proc.stdout.close()
    return Result(proc.returncode if proc.returncode is not None else -1, "\n".join(lines),
                  new_cwd[0], timed_out, cancelled)
