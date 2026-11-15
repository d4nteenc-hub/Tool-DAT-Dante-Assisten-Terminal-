# DAT — Dante Assistant Terminal

**Talk to your terminal. It does the rest.**

DAT is an AI that operates your terminal. Tell it what you want in plain language — *"clone this repo"*, *"free up my phone's storage"*, *"what's eating my disk?"* — and it writes the shell commands, runs them, reads the output, and keeps going until the job is done.

It is built for **Termux on Android**, and works in any Linux/macOS terminal. It's one Python package with **no dependencies** (standard library only), so there is nothing to `pip install`.

```
 ▓█████▄   ▄▄▄      ▄▄▄█████▓
 ▒██▀ ██▌ ▒████▄    ▓  ██▒ ▓▒
 ░██   █▌ ▒██  ▀█▄  ▒ ▓██░ ▒░     ← red goth banner, animated divider
 ─────────── † ───────────
 ● Fast · quick replies, acts now
┌─ output ──────────────────────────┐
│ dat ❯ clone github.com/user/repo  │
│  ▸ Cloning.                       │
│  $ git clone github.com/user/repo │
│  ▸ Done. It's in ~/repo.          │
└───────────────────────────────────┘
┌─ input ───────────────────────────┐
│ ❯ ask anything, or !cmd for shell │
└───────────────────────────────────┘
```

## Features

- **Does the work, not just the advice.** Runs commands, reads results, fixes errors, continues.
- **Any language.** The interface is English; the AI answers in whatever language you write. Confirmations too — answer `yes`, `ya`, `sí`, `はい`, `sikat`…
- **Bring your own key.** Works with Groq, Google Gemini, OpenRouter, OpenAI and Anthropic. Paste a key and DAT detects the provider itself.
- **Two modes.** `/fast` acts immediately. `/think` shows a plan and waits for your approval first.
- **Safety net.** Destructive commands (delete, overwrite, uninstall, force-push…) ask first. A few catastrophic ones (`rm -rf ~`, formatting disks…) are blocked outright.
- **Phone-friendly TUI.** Scrollable output box, hidden key entry, adapts to a small screen when the keyboard is open.
- **It's also a normal terminal.** Prefix any line with `!` to run it directly: `!ls -la`.

## Install

### Termux (Android)

```sh
pkg update && pkg install -y git python
git clone https://github.com/d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-.git dat
cd dat && sh install.sh
dat
```

### Linux / macOS

```sh
git clone https://github.com/d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-.git dat
cd dat && sh install.sh     # puts `dat` in ~/.local/bin
dat
```

Prefer pip? `pip install git+https://github.com/d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-.git`. Or skip installing and run `python3 -m dat` from the repo folder. Requires Python 3.8+ with `curses` (included on Termux, Linux and macOS; on Windows use WSL).

**Update:** `cd dat && git pull`. **Uninstall:** `sh install.sh --uninstall`.

## Get an API key

DAT needs an API key from an AI provider. Free options (no credit card at the time of writing):

| Provider | Where | Notes |
|---|---|---|
| **Groq** (recommended) | [console.groq.com/keys](https://console.groq.com/keys) | Fast. Free plan with rate limits per organization. |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free tier without billing. Google may use free-tier prompts to improve its products. |
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Models ending in `:free`. Roughly 50 requests/day until you've bought $10 of credits once, then 1,000/day. |
| OpenAI / Anthropic | [platform.openai.com](https://platform.openai.com/api-keys) / [console.anthropic.com](https://console.anthropic.com/) | Paid. |

Free-tier limits change often — check your provider's console. Only use a key **you created yourself**. Keys shared in groups or found on GitHub are leaked keys and get revoked.

On first launch DAT asks for the key (hidden as you type) and detects the provider from its prefix:

| Prefix | Provider |
|---|---|
| `gsk_` | Groq |
| `AIza` | Gemini |
| `sk-or-` | OpenRouter |
| `sk-ant-` | Anthropic |
| `sk-` | OpenAI |

Unknown prefix? DAT asks you to pick the provider. It then tests the key, picks a sensible default model, and saves everything.

## Using DAT

Just type what you want:

```
dat ❯ how much storage is left?
dat ❯ clone https://github.com/user/repo and install its requirements
dat ❯ find files bigger than 100MB in my downloads
dat ❯ bersihin cache hp gua
```

| Command | What it does |
|---|---|
| `/fast` | Quick replies, acts immediately |
| `/think` | Shows a plan first and waits for your OK |
| `/model` | Lists models. `/model 3` or `/model <name>` switches |
| `/key` | Change the API key or provider |
| `/clear` | Clear the screen and the AI's memory |
| `/help` | Commands and shortcuts |
| `/exit` | Quit (`Ctrl+D` also works) |
| `!cmd` | Run a shell command directly, no AI |

**Keys:** `Up/Down` scroll the output · `PgUp/PgDn` page · `Home/End` top/bottom · `Tab` completes `/commands` · `Ctrl+P/N` input history · `Esc` cancels the running task.

## Safety

DAT runs commands that an AI wrote, on your machine. Read what it's about to do.

- **Asks first:** `rm`, overwriting an existing file, uninstalling packages, `git reset --hard`, force-push, `sudo`, `curl … | sh`, `kill`, recursive `chmod`, `sed -i`, and similar.
- **Never runs:** deleting `/` or your home folder, formatting or partitioning disks, `dd` to a device, fork bombs. (You can still type those yourself with `!`.)
- **Other limits:** commands are non-interactive and time out after 5 minutes (`DAT_CMD_TIMEOUT`).

This filter is a safety net for mistakes, **not a sandbox**. A determined or confused model can still do damage with commands it doesn't recognise. Don't run DAT as root, and keep backups of things you care about.

## Privacy

- Your messages, and the **output of every command the AI runs**, are sent to the provider you chose. Don't ask it to print files with secrets.
- Your API key is stored in plain text in `~/.config/dat/config.json` (permissions `600`). Delete it any time with `dat --reset`.
- DAT itself collects nothing and has no telemetry.

## Configuration

| Setting | Purpose |
|---|---|
| `dat --config` | Print the config file path |
| `dat --reset` | Delete the saved key and settings |
| `DAT_CONFIG` | Use a different config file |
| `DAT_BASE_URL` | Point OpenAI-compatible providers at another server (a proxy, a local Ollama at `http://localhost:11434/v1`…) |
| `DAT_CMD_TIMEOUT` | Command timeout in seconds (default 300) |
| `DAT_NO_ANIM=1` | Turn the animation off (saves battery) |

## Troubleshooting

- **"Key rejected"** — wrong or revoked key. Run `/key` and paste it again.
- **"Rate limit hit"** — you used up the free tier for now. Wait, or switch model with `/model`.
- **Boxes or the banner look broken** — your terminal isn't using UTF-8. Run `export LANG=en_US.UTF-8` (DAT falls back to plain ASCII automatically in most cases).
- **"Terminal too small"** — rotate the phone or close the keyboard.
- **The AI answers but never runs anything** — small models sometimes ignore the format. Try `/model` and pick a larger one.

## Development

```sh
python3 -m unittest discover -s tests -t .     # no network needed
```

```
dat/
├── cli.py        entry point, first-run setup, slash commands
├── agent.py      system prompt, reply parsing, the run-commands loop
├── providers.py  key detection, model lists, chat calls (urllib only)
├── safety.py     command filter: ok / confirm / block
├── shell.py      command runner: live output, timeout, cwd tracking
├── ui.py         curses interface      theme.py  colors, banner, wrapping
└── config.py     config file
```

**Adding a provider:** add an entry to `PROVIDERS` in `providers.py` (OpenAI-compatible ones need only a base URL), a prefix rule in `detect()`, and a preferred model list in `_PREFER`.

## Bahasa Indonesia (singkat)

1. Di Termux: `pkg install -y git python`, lalu `git clone https://github.com/d4nteenc-hub/Tool-DAT-Dante-Assisten-Terminal-.git dat && cd dat && sh install.sh`.
2. Jalankan `dat`, tempel API key (gratis dari Groq: console.groq.com/keys). DAT mendeteksi providernya sendiri.
3. Ketik apa yang lu mau pakai bahasa biasa. Perintah berbahaya selalu minta konfirmasi, jawab `ya` / `jangan`.
4. `/think` kalau mau lihat rencana dulu, `/fast` buat langsung jalan, `!perintah` buat jalanin shell langsung.

## License

[MIT](LICENSE)
