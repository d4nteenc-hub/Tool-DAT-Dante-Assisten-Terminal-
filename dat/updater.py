"""Check GitHub for a newer DAT and update in place."""
from __future__ import annotations

import http.client
import io
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import __version__, config

REPO = "d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-"
BRANCH = "main"
VERSION_URL = "https://raw.githubusercontent.com/%s/%s/dat/__init__.py" % (REPO, BRANCH)
ZIP_URL = "https://github.com/%s/archive/refs/heads/%s.zip" % (REPO, BRANCH)
UA = "DAT-updater (terminal assistant)"
MAX_ZIP = 8 * 1024 * 1024

_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+\.py$")


class UpdateError(Exception):
    pass


def parse_version(v: str) -> Tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v)] or [0]
    while len(nums) > 1 and nums[-1] == 0:
        nums.pop()
    return tuple(nums)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _get(url: str, timeout: float, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as e:
        raise UpdateError("GitHub answered with error %d. Try again later." % e.code)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise UpdateError("Can't reach GitHub (%s). Check your connection." % (getattr(e, "reason", e),))
    if len(data) > limit:
        raise UpdateError("The download is unexpectedly large. Nothing was changed.")
    return data


def fetch_latest(url: str = VERSION_URL, timeout: float = 10) -> str:
    """Return the version number currently published on GitHub."""
    text = _get(url, timeout, 64 * 1024).decode("utf-8", "replace")
    m = _VERSION_RE.search(text)
    if not m:
        raise UpdateError("Couldn't read the version number from GitHub.")
    return m.group(1)


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def is_git_checkout(pkg_dir: Path) -> bool:
    return (pkg_dir.parent / ".git").exists() and shutil.which("git") is not None


def git_pull(root: Path, timeout: float = 120) -> None:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"], capture_output=True,
                           text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise UpdateError("git took too long. Try again, or run git pull yourself.")
    except OSError as e:
        raise UpdateError("Couldn't run git (%s)." % e)
    if p.returncode:
        tail = " ".join((p.stderr or p.stdout or "").strip().splitlines()[-3:])[:300]
        raise UpdateError("git pull failed: %s If you edited files in this folder, "
                          "commit or stash them first." % (tail or "unknown error"))


def zip_update(pkg_dir: Path, zip_url: str = ZIP_URL, timeout: float = 60) -> None:
    """Download the latest code and replace the .py files of the dat package."""
    blob = _get(zip_url, timeout, MAX_ZIP)
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise UpdateError("The download isn't a valid zip file. Nothing was changed.")
    with zf:
        marker = "dat/__init__.py"
        names = zf.namelist()
        hits = sorted((n for n in names if n == marker or n.endswith("/" + marker)), key=len)
        if not hits:
            raise UpdateError("The download doesn't look like DAT. Nothing was changed.")
        base = hits[0][:-len(marker)] + "dat/"
        files: Dict[str, bytes] = {}
        for n in names:
            name = n[len(base):] if n.startswith(base) else ""
            if _NAME_RE.match(name) and not name.startswith("test_"):
                files[name] = zf.read(n)
    init = files.get("__init__.py", b"").decode("utf-8", "replace")
    if not _VERSION_RE.search(init):
        raise UpdateError("The download doesn't look like DAT. Nothing was changed.")
    for name, src in files.items():
        try:
            compile(src, name, "exec")
        except (SyntaxError, ValueError) as e:
            raise UpdateError("The new %s has a problem (%s). Nothing was changed." % (name, e))

    backup = Path(config.config_path()).parent / ("backup-v%s" % __version__)
    try:
        backup.mkdir(parents=True, exist_ok=True)
        for name in files:
            if (pkg_dir / name).is_file():
                shutil.copy2(str(pkg_dir / name), str(backup / name))
    except OSError:
        backup = None  # a missing backup shouldn't stop the update
    staged = []
    try:
        for name, src in files.items():
            tmp = pkg_dir / (name + ".new")
            tmp.write_bytes(src)
            staged.append((tmp, pkg_dir / name))
        for tmp, dst in staged:
            os.replace(str(tmp), str(dst))
    except OSError as e:
        for tmp, _ in staged:
            try:
                tmp.unlink()
            except OSError:
                pass
        extra = " The old files are saved in %s." % backup if backup else ""
        raise UpdateError("Couldn't write to %s (%s).%s" % (pkg_dir, e.strerror or e, extra))


def installed_version(pkg_dir: Path) -> str:
    try:
        m = _VERSION_RE.search((pkg_dir / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        m = None
    return m.group(1) if m else "?"


def update(pkg_dir: Optional[Path] = None, zip_url: str = ZIP_URL) -> Tuple[str, str]:
    """Update DAT in place. Returns (method, new version)."""
    pkg_dir = pkg_dir or package_dir()
    if is_git_checkout(pkg_dir):
        git_pull(pkg_dir.parent)
        method = "git"
    else:
        zip_update(pkg_dir, zip_url)
        method = "download"
    return method, installed_version(pkg_dir)
