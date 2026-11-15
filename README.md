# DAT — Dante Assistant Terminal

An AI that operates your terminal for you. Tell DAT what you want in plain language; it works out the shell commands, runs them, reads the results, and keeps going until the job is done.

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Version 1.0.1](https://img.shields.io/badge/version-1.0.1-lightgrey)

## Features

- **Natural-language terminal control.** Describe the task in your own language; DAT replies in that language.
- **Agent loop.** DAT runs up to 5 commands per turn in one persistent shell (`cd` persists), reads the exit codes and output, fixes errors, and continues until the task is finished.
- **Five providers.** Groq, Gemini, OpenRouter, OpenAI and Anthropic. Paste a key and DAT detects the provider from its prefix and picks a sensible default model.
- **Two modes.** `/fast` acts immediately. `/think` writes a plan first and waits for your approval before running anything.
- **Safety filter.** Destructive commands ask for confirmation; catastrophic ones are blocked (see [Safety](#safety)).
- **Multilingual confirmations.** Answer "yes" or "no" in almost any language (`ya`, `gas`, `oui`, `はい`, `nggak`, ...). Ambiguous replies are classified by the model.
- **Terminal UI.** A blue curses interface with a centered banner, scrollback, input history, `/command` completion and Esc to cancel a running task. Tap the text you typed to fix a typo in place, no retyping.
- **Zero dependencies.** Pure Python standard library.
- **Termux-friendly.** Detects Termux and tells the model to use `pkg` instead of `sudo`.

## Requirements

- Python 3.8 or newer, with the `curses` module
- An API key from one of the supported providers
- An interactive terminal: Termux (Android), Linux, macOS, or WSL on Windows

Free keys are available from [Groq](https://console.groq.com/keys) and [Google AI Studio](https://aistudio.google.com/apikey).

## Installation

DAT installs the same way everywhere: prepare your terminal (Step 1), clone the repo and run the installer (Step 2), then start it (Step 3). Only Step 1 differs per platform.

### Step 1 — Prepare your terminal

Pick your platform. You need `git` and Python 3.8+.

#### Termux (Android)

Install Termux from [F-Droid](https://f-droid.org/packages/com.termux/) (the Play Store build is outdated). Then:

```sh
pkg update && pkg upgrade -y
pkg install -y git python
```

Optional, to let DAT reach your phone's files (`~/storage`, `/sdcard`):

```sh
termux-setup-storage
```

#### Debian / Ubuntu / Kali / Linux Mint

```sh
sudo apt update
sudo apt install -y git python3
```

#### Fedora

```sh
sudo dnf install -y git python3
```

#### Arch / Manjaro

```sh
sudo pacman -S --needed git python
```

#### macOS

```sh
xcode-select --install     # provides git and python3
```

Or with Homebrew: `brew install git python`.

#### Windows (WSL)

Native Windows has no `curses`, so use WSL. In PowerShell (as Administrator):

```powershell
wsl --install
```

Restart, open the Ubuntu app, then follow the **Debian / Ubuntu** steps above inside it.

#### Check it worked

```sh
git --version
python3 --version                  # must be 3.8 or newer
python3 -c "import curses" && echo "curses OK"
```

If the last command prints an error instead of `curses OK`, install the full Python package for your system (on Windows without WSL, `pip install windows-curses` may also work).

### Step 2 — Install DAT

```sh
git clone https://github.com/d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-.git
cd Tool-DAT-Dante-Assisten-Terminal-
sh install.sh
```

The installer checks your Python version and `curses` support, then creates a `dat` launcher in `~/.local/bin` (or `$PREFIX/bin` on Termux). On Termux it installs Python for you if it is missing.

> **Keep the cloned folder.** The launcher runs DAT from it, so deleting the folder breaks the `dat` command.

**Linux / macOS only:** if the installer says to add `~/.local/bin` to your `PATH`, run the line for your shell, then restart the terminal:

```sh
# bash (most Linux)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# zsh (macOS default)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

On Termux this step isn't needed.

### Step 3 — Run it

```sh
dat
```

Prefer not to install? Run it straight from the cloned folder:

```sh
python3 -m dat
```

### Update and uninstall

- **Update:** `cd` into the cloned folder and run `git pull`.
- **Uninstall:** run `dat --reset` first if you want to delete your saved key, then `sh install.sh --uninstall` from the cloned folder.

## Quick start

1. Run `dat`.
2. Paste your API key when asked. Input is hidden. DAT detects the provider, tests the connection and picks a default model.
3. Type what you want done:

```
you > create a folder called notes and put an empty todo.md in it
you > find the 5 largest files in this directory
you > install ripgrep
```

Prefix a line with `!` to run a shell command directly, with no AI involved: `!ls -la`.

## Commands

| Command | What it does |
| --- | --- |
| `/fast` | Quick replies; acts immediately |
| `/think` | Plans first, then acts after you approve |
| `/model` | List available models. `/model <n>` or `/model <name>` switches; `/model list <text>` filters |
| `/key` | Change the API key or provider |
| `/clear` | Clear the screen and the AI's memory of the conversation |
| `/help` | Show the command list |
| `/exit` | Quit (`/quit`, `/q` and Ctrl+D also work) |
| `!cmd` | Run a shell command directly |

### Keys

| Key | Action |
| --- | --- |
| Left / Right | Move the cursor in the input |
| Tap on the input text | Put the cursor right after the tapped letter, so Backspace removes it and you can type the fix |
| Tap `‹` / `›` | Scroll a long input left / right |
| Mouse wheel / swipe | Scroll the output |
| Up / Down | Scroll the output |
| PgUp / PgDn | Scroll a page |
| Home / End | Jump to top / bottom |
| Tab | Complete a `/command` |
| Ctrl+P / Ctrl+N | Input history |
| Esc | Cancel the running task |

The output panel fills from the top. A scrollbar and the "more" hints only appear once the output no longer fits.

### Command-line options

```
dat --version    print the version
dat --config     print the config file path and exit
dat --reset      delete the saved API key and settings
```

## Providers

| Provider | Key prefix | Default model preference |
| --- | --- | --- |
| Groq | `gsk_` | `openai/gpt-oss-120b`, then `llama-3.3-70b-versatile` |
| Gemini | `AIza` | `gemini-2.5-flash` |
| OpenRouter | `sk-or-` | `openrouter/free`, then any `:free` model |
| OpenAI | `sk-` | `gpt-5-mini`, then `gpt-4.1-mini` / `gpt-4o-mini` |
| Anthropic | `sk-ant-` | a Haiku model, then Sonnet |

If the key format isn't recognised, DAT asks you to pick the provider from a list. You can change the model at any time with `/model`.

## Safety

Every command the AI proposes goes through a filter before it runs.

**Blocked** (never run; the model is told to ask you to use `!cmd` if you really want it):

- `rm` on critical locations such as `/`, your home folder, `/etc`, `/usr`, `/sdcard`, or `--no-preserve-root`
- `dd` to a device, `mkfs*`, `fdisk`, `parted` and other disk tools, redirects into disk devices
- recursive `chmod` / `chown` on system or home folders
- fork bombs

**Asks first** (you answer yes or no):

- `rm`, `rmdir`, `unlink`, `shred`, `truncate`, `find -delete`
- `mv` / `cp` / `tee` / `>` that would overwrite an existing file, and `sed -i`
- destructive `git` operations: `reset --hard`, `clean -f`, force-push, `checkout .`, `branch -D`, `stash drop`
- removing packages, killing processes, reboot or shutdown
- anything run as root (`sudo`, `su`, `doas`) and `curl ... | sh` style scripts

Things to keep in mind:

- The filter is a heuristic safety net, not a sandbox. Read the commands DAT shows before approving, especially in `/fast` mode.
- `!cmd` runs your command as-is, **without** the filter.
- Command output (truncated to about 2,500 characters per command) is sent to your chosen AI provider so it can continue the task. Don't run DAT on commands that print secrets.

## Configuration

Your provider, key, model and mode are stored in a JSON file, created with owner-only permissions (`0600`, in a `0700` folder):

```
~/.config/dat/config.json      # or $XDG_CONFIG_HOME/dat/config.json
```

Run `dat --config` to print the exact path. The key stays on your device and is only sent to the provider you chose.

### Environment variables

| Variable | Effect |
| --- | --- |
| `DAT_CONFIG` | Use a different config file path |
| `DAT_BASE_URL` | Override the API base URL for OpenAI-compatible providers (Groq, Gemini, OpenRouter, OpenAI), e.g. for a proxy or local server |
| `DAT_CMD_TIMEOUT` | Per-command timeout in seconds (default `300`) |
| `DAT_NO_ANIM` | Set to any value to turn off UI animation |
| `DAT_NO_MOUSE` | Set to any value to turn off tap and wheel support (e.g. if it gets in the way of selecting text) |

## How it works

DAT gives the model a system prompt describing your environment (OS, shell, Termux, home, current directory, date) and asks it to reply with a single JSON object: a short message, a list of commands, and a `done` flag. DAT runs the commands, sends back exit codes and output, and repeats. A task is capped at 8 steps in `/fast` mode and 14 in `/think` mode; say "continue" to go on. The model sees the last 20 messages of the conversation. Rate limits and server errors are retried automatically with backoff.

## Project layout

```
dat/
  cli.py        entry point, slash commands, first-run setup
  agent.py      prompt, agent loop, reply parsing, yes/no handling
  providers.py  Groq / Gemini / OpenRouter / OpenAI / Anthropic clients
  safety.py     command safety filter
  shell.py      persistent-cwd shell runner with timeout and cancel
  config.py     config file load / save / reset
  ui.py         curses terminal UI
  theme.py      colours, text width and wrapping
tests/          unit tests
install.sh      launcher installer
pyproject.toml  package metadata
```

## Development

Run the tests (standard library only):

```sh
python3 -m unittest discover
```

## License

MIT. See [LICENSE](LICENSE).
