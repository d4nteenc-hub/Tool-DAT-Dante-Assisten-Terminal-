from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import List, Optional

_RANK = {"ok": 0, "confirm": 1, "block": 2}


@dataclass
class Verdict:
    level: str = "ok"
    reason: str = ""


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
_SPLIT = re.compile(r"\|\||&&|;|\||(?<![>&])&(?!>)|\n")
_SUBSHELL = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_REDIR = re.compile(r"(?<![>&\d])>(?![>&|])\s*(\"[^\"]*\"|'[^']*'|[^\s;&|<>]+)")
_PIPE_SH = re.compile(r"\b(curl|wget)\b[^\n]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b")
_FORK = re.compile(r":\s*\(\s*\)\s*\{")
_WRAPPERS = {"nohup", "time", "command", "exec", "env", "nice", "xargs", "stdbuf"}
_ROOT = {"sudo", "su", "tsu", "doas"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ash"}
_PKG = {"pkg", "apt", "apt-get", "dpkg", "pip", "pip3", "npm", "pnpm", "yarn", "gem", "cargo", "brew"}
_PKG_REMOVE = {"remove", "uninstall", "purge", "autoremove", "erase", "--remove", "--purge", "-r", "-P"}
_DISK = {"wipefs", "fdisk", "sfdisk", "parted", "mke2fs", "diskutil"}
_SAFE_DEV = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}


def _critical_paths() -> set:
    home = os.path.expanduser("~")
    crit = {"/", home, "/data", "/data/data", "/sdcard", "/storage", "/storage/emulated",
            "/storage/emulated/0", "/system", "/usr", "/bin", "/sbin", "/etc", "/var", "/home",
            "/root", "/lib", "/opt", "/boot", "/dev"}
    prefix = os.environ.get("PREFIX")
    if prefix:
        crit.add(os.path.normpath(prefix))
    return crit


def _abs(path: str, cwd: str) -> str:
    p = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return p


def _is_critical(path: str, cwd: str) -> bool:
    p = _abs(path, cwd)
    if p.endswith("/*"):
        p = p[:-2]
    p = p.rstrip("/") or "/"
    return os.path.normpath(p) in _critical_paths()


def _flags(args: List[str]):
    short, long_ = set(), set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            long_.add(a)
        elif a.startswith("-") and len(a) > 1:
            short.update(a[1:])
    return short, long_


def _targets(args: List[str]) -> List[str]:
    out, after = [], False
    for a in args:
        if after or not a.startswith("-"):
            out.append(a)
        elif a == "--":
            after = True
    return out


def _worst(found: List[Verdict]) -> Verdict:
    top = max((_RANK[v.level] for v in found), default=0)
    if top == 0:
        return Verdict()
    level = "block" if top == 2 else "confirm"
    reasons: List[str] = []
    for v in found:
        if _RANK[v.level] == top and v.reason and v.reason not in reasons:
            reasons.append(v.reason)
    return Verdict(level, "; ".join(reasons[:3]))


def _redirects(seg: str, cwd: str) -> List[Verdict]:
    out = []
    for m in _REDIR.finditer(seg):
        t = m.group(1).strip("\"'")
        if t in _SAFE_DEV or t.startswith("&"):
            continue
        if re.match(r"/dev/(sd|nvme|mmcblk|block|vd|loop)", t):
            out.append(Verdict("block", "writes to a disk device"))
        elif os.path.isfile(_abs(t, cwd)):
            out.append(Verdict("confirm", "overwrites " + t))
    return out


def _rules(prog: str, args: List[str], cwd: str, depth: int) -> Verdict:
    short, long_ = _flags(args)
    targets = _targets(args)
    if prog in _SHELLS and "-c" in args and depth < 3:
        i = args.index("-c")
        return check(args[i + 1], cwd, depth + 1) if i + 1 < len(args) else Verdict()
    if prog == "eval" and depth < 3:
        return check(" ".join(args), cwd, depth + 1)
    if prog == "rm":
        for t in targets:
            if _is_critical(t, cwd):
                return Verdict("block", "refuses to delete " + t)
        if "--no-preserve-root" in long_:
            return Verdict("block", "refuses --no-preserve-root")
        rec = "r" in short or "R" in short or "--recursive" in long_
        return Verdict("confirm", "deletes files" + (" recursively" if rec else ""))
    if prog in ("rmdir", "unlink"):
        return Verdict("confirm", "removes " + ("directories" if prog == "rmdir" else "a file"))
    if prog == "dd":
        if any(a.startswith("of=/dev/") for a in args):
            return Verdict("block", "dd to a device")
        return Verdict("confirm", "dd can overwrite data")
    if prog.startswith("mkfs") or prog in _DISK:
        return Verdict("block", "formats or partitions a disk")
    if prog in ("shred", "truncate"):
        return Verdict("confirm", "destroys file contents")
    if prog in ("chmod", "chown", "chgrp") and ("R" in short or "r" in short or "--recursive" in long_):
        if any(_is_critical(t, cwd) for t in targets[1:]):
            return Verdict("block", "recursive change on a system or home folder")
        return Verdict("confirm", "recursive permission change")
    if prog in ("kill", "pkill", "killall"):
        return Verdict("confirm", "stops processes")
    if prog in ("reboot", "shutdown", "poweroff", "halt"):
        return Verdict("confirm", "restarts or powers off")
    if prog in _PKG and any(a in _PKG_REMOVE for a in args):
        return Verdict("confirm", "removes packages")
    if prog == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        rest = args[args.index(sub) + 1:] if sub else []
        if sub == "reset" and "--hard" in rest:
            return Verdict("confirm", "discards uncommitted work")
        if sub == "clean" and any(a.startswith("-") and "f" in a for a in rest):
            return Verdict("confirm", "deletes untracked files")
        if sub == "push" and any(a in ("-f", "--force", "--force-with-lease", "--delete") for a in rest):
            return Verdict("confirm", "force-pushes or deletes remote refs")
        if sub in ("checkout", "restore") and ("." in rest or "--" in rest):
            return Verdict("confirm", "discards local changes")
        if sub == "branch" and "-D" in rest:
            return Verdict("confirm", "deletes a branch")
        if sub == "stash" and any(a in ("drop", "clear") for a in rest):
            return Verdict("confirm", "drops stashed work")
    if prog == "find" and ("-delete" in args or any(a in ("rm", "shred") for a in args)):
        return Verdict("confirm", "deletes files")
    if prog in ("sed", "perl") and ("i" in short or "--in-place" in long_):
        return Verdict("confirm", "edits files in place")
    if prog in ("mv", "cp") and "n" not in short and "--no-clobber" not in long_ and len(targets) == 2:
        if os.path.isfile(_abs(targets[1], cwd)):
            return Verdict("confirm", "overwrites " + targets[1])
    if prog == "tee" and "a" not in short and any(os.path.isfile(_abs(t, cwd)) for t in targets):
        return Verdict("confirm", "overwrites a file")
    return Verdict()


def _segment(seg: str, cwd: str, depth: int) -> Verdict:
    try:
        toks = shlex.split(seg)
    except ValueError:
        toks = seg.split()
    root = False
    while toks and (re.match(r"^[A-Za-z_]\w*=", toks[0]) or toks[0] in _WRAPPERS or toks[0] in _ROOT):
        root = root or toks[0] in _ROOT
        toks = toks[1:]
    if not toks:
        return Verdict("confirm", "runs as root") if root else Verdict()
    v = _rules(os.path.basename(toks[0]), toks[1:], cwd, depth)
    if root and v.level == "ok":
        v = Verdict("confirm", "runs as root")
    return v


def check(cmd: str, cwd: Optional[str] = None, _depth: int = 0) -> Verdict:
    cwd = cwd or os.getcwd()
    text = _HEREDOC.sub("", cmd)
    found: List[Verdict] = []
    if _FORK.search(text):
        found.append(Verdict("block", "fork bomb"))
    if _PIPE_SH.search(text):
        found.append(Verdict("confirm", "runs a downloaded script"))
    if _depth < 3:
        for m in _SUBSHELL.finditer(text):
            inner = m.group(1) or m.group(2)
            if inner and inner.strip():
                found.append(check(inner, cwd, _depth + 1))
    for seg in _SPLIT.split(text):
        seg = seg.strip()
        if seg:
            found.extend(_redirects(seg, cwd))
            found.append(_segment(seg, cwd, _depth))
    return _worst(found)
