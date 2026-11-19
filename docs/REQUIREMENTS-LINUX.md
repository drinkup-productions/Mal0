# Running MalO on Linux

Target verified: **CachyOS (Arch), KWin/Wayland, Python 3.14** — every aspect below was
exercised there on 2026-11-19 except where marked *not installed here*.

## One-time setup

```sh
cd MalO
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt     # pillow, websockets, rapidocr-onnxruntime
npm install                                    # node bridge SDK (package.json)
./start.sh                                     # or: .venv/bin/python -m malo --broker
```

Data dir is `$MALO_DATA` or `~/MalOAvatar` (config.json, broker token, personas, logs).
First start pairs the machine (`python -m malo --pair desktop`) if no `broker_token`.

## Agent backend (worker)

The worker that runs agent turns is selected by `"backend"` in config.json:

| `"backend"` | Worker child | Needs |
|---|---|---|
| `""` (default) — legacy Letta bridge | `python -m malo.worker` → node `bridge.mjs` → Letta server ws://127.0.0.1:4500 | `npm install` in the repo **and** a running Letta server (`pip install letta-ai`; start.sh starts one when :4500 is free) |
| `"omp"` — OMP RPC | `omp --mode rpc-ui`, JSONL RPC over stdio, adapted by `malo/core/ompworker.py` | only the `omp` binary on PATH (here: `~/.local/bin/omp`). No node, no Letta |

OMP backend options in config.json: `"omp_bin"` (binary path; default `omp` on PATH),
`"omp_model"` (`--model` override), `"omp_args"` (extra raw args, e.g. `["--provider", "x"]`).
Session continuity across respawns: after ready the worker persists OMP's session file in
`"omp_session"` and resumes it on every respawn; persona.md is synced to
`<workspace>/.omp/AGENTS.md` before each spawn. Permission mapping: confirm-on →
`--approval-mode write` (execs prompt), confirm-off → `yolo`.

Verified live on this box 2026-11-19 with backend=omp against the local model at
127.0.0.1:1234: spawn→ready in 0.3 s, thinking + text streamed per frame, turn done in
~29 s; host tools mounted via set_host_tools (4 registry names skipped for colliding
with OMP builtins); session file persisted and persona synced byte-exact. The legacy
bridge now also fails *visibly* instead of as a silent timeout: bridge start errors are
emitted as structured `error`/`dead` worker events (a `_out()` arity bug that masked
them is fixed in `malo/worker.py`).

## System packages per aspect

| Aspect | Package(s) — Arch/pacman | Status on this box |
|---|---|---|
| Python + Tk GUI (window, avatar, overlay sprite) | `python3-tk` | OK |
| Audio playback (SFX, voice) | `mpv` or `ffmpeg` (ffplay); fallbacks `aplay`, `paplay` | OK (ffplay) |
| Screen capture | KDE: `spectacle`; wlroots: `grim`; X11: `scrot` | OK (spectacle, 1920x1080 verified) |
| OCR (`screen_ocr`) | pip `rapidocr-onnxruntime` (in requirements.txt) | OK ("HELLO MALO LINUX" @ 0.90) |
| Mouse/keyboard input injection (Wayland) | `ydotool`, then add user to group: `sudo usermod -aG uinput $USER` + re-login | *not installed here* — tools report failure cleanly until set up |
| Mouse/keyboard input (X11/XWayland sessions only) | `xdotool` | n/a under KWin Wayland |
| Window list / focus (`windows`, `focus_window`) | X11: `xdotool`. **No clean CLI exists for native Wayland** — these tools return empty/false there by design | *not installed here* |
| Desktop notifications | `libnotify` (notify-send) | OK |
| MCP servers (fetch, playwright, ddg) | `nodejs-npm` (npx), `uv`/`uvx` for the uvx-based ones; `~/.local/bin` must be on PATH | OK — all 3 up after `uv` install |
| Letta agent server — only for `"backend": ""` (see Agent backend above) | pip `letta-ai` (`pip install -U letta-ai`) | *not installed here*; the OMP backend needs none of this, start.sh warns and continues |
| Self-dev snapshots / git tooling | `git` | OK |

## Launchers

* `start.sh [--no-app] [--headless] [--port=N] [--broker-port=N]` — preflight
  (python3 + node required; letta warned), starts the Letta server on :4500 if free,
  pairs the broker token if missing, then runs the app (`--broker`, plus `--server`
  when headless). Log: `$MALO_DATA/letta-server.log`.
* `restart.sh [delay]` — touches `$MALO_DATA/quit.flag` (the app's graceful shutdown
  watches it), waits up to 120 s, SIGKILL on timeout, relaunches start.sh detached.
  Log: `$MALO_DATA/restart.log`.

## Known limitations on Linux (documented, not bugs)

* **Tray icon**: the Windows tray was pystray/appindicator-based (X11 protocol). KDE
  Wayland expects StatusNotifier over D-Bus, which pystray does not implement — so no
  tray under Wayland; the app runs window-only (`--no-tray` still accepted). X11
  sessions could get it back with `pystray` + `libappindicator`.
* **uia_* tools** (accessibility tree): they wrap Windows UIAutomation. Kept registered
  so personas/prompts stay stable; on Linux every call returns a clean error dict.
* **Overlay fullscreen auto-hide**: uses user32, guarded off — the overlay sprite never
  auto-hides on Linux.
* **Multi-monitor**: capture is one full output (`spectacle -b`); `screens()` reports a
  single screen sized from the last successful grab (cold start falls back to grabbing
  directly).
* **Input injection under Wayland** requires ydotool + uinput group membership (kernel
  sandbox: no compositor can let an app move the global cursor otherwise).

## Data/config note

`mcp_servers.json` in this repo is only a template; live config lives in the data dir.
The live file on this box previously pointed at `%USERPROFILE%\.local\bin\uvx.exe` —
corrected to bare `uvx`, and the hardcoded defaults in `malo/tools/mcp.py` were fixed
the same way so fresh Linux installs start clean. The template's `desk-mcp` entry
references a binary whose origin is unknown (not on PATH, not in package.json); it is
absent from this box's live config, so nothing runs unless you add the server back —
supply the binary or delete the entry if you do.
