#!/usr/bin/env sh
set -eu

DIR=$(cd "$(dirname "$0")" && pwd)

if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ]; then
  BIN="$PREFIX/bin"
  SHEBANG="#!$PREFIX/bin/sh"
else
  BIN="$HOME/.local/bin"
  SHEBANG="#!/bin/sh"
fi
LAUNCHER="$BIN/dat"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$LAUNCHER"
  echo "Removed $LAUNCHER"
  echo "Your API key is still saved. Delete it with: dat --reset (before uninstalling)"
  exit 0
fi

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  if command -v pkg >/dev/null 2>&1; then
    echo "Installing Python..."
    pkg install -y python
    PY=$(command -v python3)
  else
    echo "Python 3.8+ was not found. Install it, then run this again." >&2
    exit 1
  fi
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' ||
  { echo "Python 3.8 or newer is required." >&2; exit 1; }
"$PY" -c 'import curses' 2>/dev/null ||
  { echo "This Python has no curses module (Windows? use WSL or Termux)." >&2; exit 1; }

mkdir -p "$BIN"
cat > "$LAUNCHER" <<EOF
$SHEBANG
PYTHONPATH="$DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m dat "\$@"
EOF
chmod +x "$LAUNCHER"

echo "Installed: $LAUNCHER"
case ":$PATH:" in
  *":$BIN:"*) echo "Run: dat" ;;
  *) echo "Add this to your shell profile, then restart the shell:"
     echo "  export PATH=\"$BIN:\$PATH\"" ;;
esac
echo "Keep this folder: the launcher runs from it ($DIR)."
if [ -d "$DIR/.git" ]; then
  echo "Update later with: cd \"$DIR\" && git pull"
fi
