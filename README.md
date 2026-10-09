# gateaway-tele-opencode

A Telegram bot that runs [OpenCode](https://opencode.ai) on your VPS.
Messages from Telegram (DM / group / forum topic) execute as OpenCode
prompts on the server. Replies come back to Telegram.

```
Telegram ──polling──► gateway.py ──HTTP──► opencode serve (private :4097)
```

## Requirements

- Ubuntu/Debian VPS (or any distro with systemd), sudo access
- Python 3.10+ (stdlib only, no pip dependencies) + `curl`
- OpenCode CLI v2 installed (`opencode --version` works) with a logged-in
  provider (`opencode auth list` — without this the agent cannot answer)
- `git` (to clone this repo)
- A Telegram account

Optional:

- `warp-cli` (Cloudflare WARP) — for `/proxy` and `/rotate`
- One of: `whisper` CLI, `GROQ_API_KEY`, or `OPENAI_API_KEY` — for voice
  note transcription. Without any of these, audio is forwarded as a file.

## Install from scratch

```bash
# 1. clone
git clone https://github.com/pamungkasxd02-star/gateaway-tele-opencode
cd gateaway-tele-opencode

# 2. secrets (never commit this file)
cp .env.example .env
nano .env
chmod 600 .env
```

Minimum `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_ALLOWED_USERS=123456789
```

Get the token from [@BotFather](https://t.me/BotFather) (`/newbot`).
Get your numeric user ID from [@userinfobot](https://t.me/userinfobot).
Optional in `.env`: `TELEGRAM_HOME_CHANNEL`,
`TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_GROUP_ALLOWED_USERS`,
`TELEGRAM_CRON_THREAD_ID`, `TELEGRAM_NOTIFICATIONS=all`,
`GROQ_API_KEY`, `OPENAI_API_KEY`.

```bash
# 3. install the service
sudo cp oc-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oc-telegram
sudo systemctl status oc-telegram

# 4. logs + test
tail -f gateway.log
```

The bundled `oc-telegram.service`:

```ini
[Unit]
Description=OpenCode Telegram Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/oc-gateway
Environment=PATH=/home/ubuntu/.local/bin:/home/ubuntu/.opencode/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=HOME=/home/ubuntu
EnvironmentFile=-/home/ubuntu/oc-gateway/.env
ExecStart=/usr/bin/python3 /home/ubuntu/oc-gateway/gateway.py
Restart=always
RestartSec=5
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
```

Adjust `User=` and paths to your machine. Test: message the bot.

Group notes: BotFather → Bot Settings → *Group Privacy* → **Turn off**,
then remove and re-add the bot to the group, and set
`TELEGRAM_GROUP_ALLOWED_CHATS`.

## How replies work

Each user message triggers one agent turn. During a turn there are two
bubbles:

- **Progress bubble** (separate message, silent): one line per tool call
  (`💻 Running "date +%Y"`), terminal calls as code blocks.
- **Answer bubble**: starts at `💭 Thinking…`, edited as text streams in,
  always replies to the triggering message. The final answer renders as
  Telegram HTML (bold/italic/code/links/quotes/tables) plus a footer:
  `model · context% · ~/cwd · duration`.

Other rules:

- Rapid messages (< 4s apart, `batching.hold_sec`) merge into one turn.
- Replies over 3800 chars split into `(1/3)` pages.
- An answer that is exactly `[SILENT]`/`NO_REPLY` (or similar) is not
  sent (for automation).
- Dangerous-looking prompts raise an approval card (✅/❌ buttons, or
  `/approve` · `/deny`).
- Progress notifications are silent by default (`important`); `all`
  rings for everything.
- On flood 429: wait `retry_after`, retry once.
- `/restart` waits for active turns (max 150s), then confirms after boot.

## Commands

| Command | What it does |
|---|---|
| `/help` | list all commands |
| `/start` | help + show quick buttons |
| `/keyboard` | show the persistent quick buttons |
| `/menu` | inline buttons (Models/Sessions/Agents/Status/Cron/Limits/Stats/MCP/Help) |
| `/new` · `/reset` | new conversation (this chat only) |
| `/retry` | re-run the last message |
| `/undo` | revert the last exchange |
| `/compress` · `/compact` | compact context |
| `/title [name]` · `/rename` | session title |
| `/resume [name]` | resume a named session |
| `/sessions` · `/session id` | list / jump sessions |
| `/stop` | stop the running turn |
| `/bg <prompt>` | background task, result delivered back |
| `/btw <question>` | side question (branched session, deleted after) |
| `/branch [name]` | fork the session here |
| `/model [provider:model]` · `/models` | show/change model |
| `/agents` · `/agent [name]` | list/change agent |
| `/personality [name]` · `/reasoning on\|off` | persona / reasoning display |
| `/status` · `/usage` · `/context` · `/whoami` | session info and tokens |
| `/stats` · `/insights` | opencode stats (same) |
| `/mcp` · `/auth` · `/plugins` · `/update` | mirror the opencode CLI |
| `/commands` · `/run <name>` · `/skills` | OpenCode commands/skills |
| `/diff` · `/export` | session diff / download session as file |
| `/init` · `/review [target]` | AGENTS.md setup / review changes |
| `/goal <text>` | standing goal: keeps working until done |
| `/goal status\|pause\|resume\|clear` · `/subgoal ...` | manage the goal |
| `/loop 5m ... [--times N]` · `/loop status\|stop id` | repeat a prompt in this session |
| `/heartbeat every 5m ...` | recurring prompt, idle sessions only |
| `/queue <prompt>` | queue for the next turn |
| `/steer <note>` | steer the next turn |
| `/plan <task>` | write a plan to file, no execution |
| `/cron add <expr> <prompt>` · `/cron list\|rm\|on\|off` | schedule to the home channel |
| `/proxy [on\|off]` · `/rotate` · `/limits` · `/egress` | WARP + rate limits |
| `/sethome` · `/platforms` | home channel · gateway status |
| `/approve` · `/deny` | approve/reject a dangerous prompt |
| `/footer on\|off` · `/config` | reply footer · view config |
| `/restart` | graceful gateway restart |
| `/<skill-name>` | unknown commands run as agent skills |

Cron format: `1m|30m|2h|1d` (min 1m), `every 30m`, `daily 07:00`, or
5-field cron (`*/15 * * * *`). Set `/sethome` first so results have a
destination. Example: `/cron add 30m check BTC price and summarize`.

Example goal: `/goal fix all failing tests` — a judge scores each turn
(`DONE/CONTINUE/BLOCKED`) and the loop continues automatically. Default
budget 20 turns (`goals.max_turns`). `/goal pause` stops the loop any time.

WARP control: `/proxy` shows status (switch, warp-cli, proxied vs direct
IP); `/proxy on|off` switches + restarts the server; `/proxy auto on|off`
toggles auto-rotate on rate limits (default ON — rotates egress IP and
retries the turn once, 5-min cooldown against flapping); `/rotate` rotates
manually (reports old → new); `/limits` shows per-model rate-limit hits.

## Files and media

Inbound: voice/audio transcribed when STT is available, otherwise
forwarded as files. Photos and documents attach as native vision/file
input. If the model refuses an image, one retry runs on
`vision.fallback_model` without changing your model/session.

Outbound: text first, then attachments. The agent attaches with a
`MEDIA:/path` tag (workspace-relative allowed), or automatically: files
created/changed during the turn and mentioned in the reply attach
themselves (max 5/turn, max 48MB/file). Agent rules live in
`oc-workspace/AGENTS.md`.

Groups: the bot stays silent without a mention (needs `require_mention`
+ privacy OFF). `observe_unmentioned_group_messages: true` stores plain
chatter as context without running the agent. `group_allow_from`
(`TELEGRAM_GROUP_ALLOWED_USERS`) allows specific senders in groups only,
no DM access. `ignored_threads` mutes specific topics.

`/setinline` in BotFather + `inline_mode: true` enables the picker: type
`@botname <search>` in any chat to find commands/skills. `base_url` /
`base_file_url` point at a local Bot API server (file limit 20MB → 2GB).

## Multi-profile routing

Route chats/threads to different workspaces/models/timeouts in
`config.json`:

```json
"gateway": {
  "routing": {
    "default_profile": "default",
    "rules": [
      {"chat_id": "-1001234567890", "thread_id": "5", "profile": "work"}
    ]
  },
  "profiles": {
    "default": {"workspace": "~/oc-workspace", "model": "", "agent": "", "auto_approve": true, "timeout_sec": 900},
    "work":    {"workspace": "~/work-area", "model": "opencode/big-pickle", "agent": "", "auto_approve": true, "timeout_sec": 1800}
  }
}
```

## Webhook (optional)

Default is long polling (fits always-on VPS). For cloud hosting that
wakes on inbound traffic:

```json
"webhook": {"enabled": true, "url": "https://your-domain/telegram", "secret": "openssl-rand-hex-32-output", "port": 8443}
```

## Security — read this

Anyone who can chat with the bot can execute commands on the server
(the agent has shell and file access). Therefore:

1. `TELEGRAM_ALLOWED_USERS` is required. Empty = every message rejected.
2. Never share the bot token. Leaked → `/revoke` in BotFather, replace
   `.env`, restart the service.
3. `chmod 600` on `config.json` and `.env`. Neither secret ships in git
   (`config.json` holds no secrets — the token stays `${TELEGRAM_BOT_TOKEN}`).
4. For tighter isolation, run the service as a dedicated Linux user with
   limited access and point `workspace` at that user's directory.

## Troubleshooting

| Symptom | Check |
|---|---|
| Bot silent | `systemctl status oc-telegram`, `tail gateway.log` |
| 401 Unauthorized | wrong token in `.env` |
| "access denied" | user ID missing from `TELEGRAM_ALLOWED_USERS` |
| Dead in groups | Group Privacy OFF + bot re-added + `TELEGRAM_GROUP_ALLOWED_CHATS` |
| `/` suggestions missing | force-close the Telegram app, type `/` alone (letters filter the list) |
| "Thinking…" for minutes | slow model — `/stop`, switch `/model`, or `/compress`/`/new` on bloated context |
| Long replies split | normal — `(1/3)` pages, files after text |

## Files in this repo

```
gateway.py    # entry point: main/polling/webhook
core.py       # config/state/log
tg.py         # Telegram transport
render.py     # answer rendering to Telegram HTML
pipeline.py   # turn queue, cron/loop/heartbeat, STT, goal engine
commands.py   # all commands + buttons
dispatch.py   # Telegram update routing
executor.py   # OpenCode HTTP API client + private :4097 server
config.json   # profiles/routing (no secrets)
.env.example  # .env template
oc-telegram.service  # systemd unit
```

Runtime (not in git): `.env`, `state.json`, `gateway.log`,
`~/.cache/oc-gateway/` (downloaded media).

## Architecture

The gateway never spawns `opencode run`. It manages its own private
OpenCode server (port 4097, random password in `.server_password`) and
uses the native HTTP API:

| Command | Endpoint |
|---|---|
| send message (+ files) | `POST /api/session/{id}/prompt` |
| `/new` | `POST /api/session` |
| `/compress` | `POST /api/session/{id}/compact` |
| `/stop` | `POST /api/session/{id}/interrupt` |
| `/undo` | `DELETE /api/session/{id}/revert` |
| `/approve` `/deny` | `POST /api/session/{id}/permission/{rid}/reply` + local danger gate |
| `/btw` | `POST /api/session/{id}/fork` |
| `/usage` `/context` | `GET /api/session/{id}` (native tokens) |
| `/model` | `POST /api/session/{id}/model` |
| `/sessions` | `GET /api/session` |
| `/init` `/review` via `/run` | `POST /api/session/{id}/command` |
