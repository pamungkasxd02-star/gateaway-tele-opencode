#!/usr/bin/env python3
"""Core: path, log, config (load/save), state, identitas bot, helper kecil.

Tak import modul gateway lain (hindari circular import).
"""

import html as _html
import json
import os
import re
import sys
import threading
import time


BASE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(BASE, "config.json")
STATE_PATH = os.path.join(BASE, "state.json")
LOG_PATH = os.path.join(BASE, "gateway.log")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "oc-gateway")


DEFAULT_CFG = {
    "telegram": {
        "bot_token": "${TELEGRAM_BOT_TOKEN}",
        "allowed_users": [],
        "allowed_chats": [],
        "group_allowed_chats": [],
        "home_channel": "",
        "proxy_url": "",
        "require_mention": True,
        "mention_patterns": [],
        "observe_unmentioned_group_messages": False,
        "ignored_threads": [],
        "exclusive_bot_mentions": True,
        "bots_require_mention": True,
        "allow_bots": False,
        "status_indicator": False,
        "drop_pending_on_cold_boot": True,
        "batching": {"enabled": True, "hold_sec": 4},
        "group_allow_from": [],
        "cron_thread_id": "",
        "notifications": "important",
        "inline_mode": False,
        "base_url": "",
        "base_file_url": "",
        "footer": True,
        "max_tools_shown": 6,
        "pin_while_working": True,
        "reply_to_trigger": True,
        "command_menu": [
            {"command": "help", "description": "Show all commands"},
            {"command": "new", "description": "Start a fresh conversation"},
            {"command": "reset", "description": "Start a fresh conversation"},
            {"command": "retry", "description": "Retry the last message"},
            {"command": "undo", "description": "Remove the last exchange"},
            {"command": "compress", "description": "Compress conversation context"},
            {"command": "model", "description": "Show or change model"},
            {"command": "models", "description": "Pick model (buttons)"},
            {"command": "agents", "description": "Pick agent (buttons)"},
            {"command": "personality", "description": "Set a personality"},
            {"command": "reasoning", "description": "Toggle reasoning display"},
            {"command": "sessions", "description": "List or switch sessions"},
            {"command": "resume", "description": "Resume a named session"},
            {"command": "title", "description": "Set the session title"},
            {"command": "status", "description": "Show session info"},
            {"command": "usage", "description": "Token usage this session"},
            {"command": "insights", "description": "Usage insights"},
            {"command": "whoami", "description": "Show your access"},
            {"command": "stop", "description": "Stop the running agent"},
            {"command": "bg", "description": "Run prompt in background"},
            {"command": "btw", "description": "Ask a side question"},
            {"command": "mcp", "description": "List MCP servers"},
            {"command": "auth", "description": "Provider auth status"},
            {"command": "plugins", "description": "List plugins"},
            {"command": "menu", "description": "Button menu"},
            {"command": "keyboard", "description": "Show quick buttons"},
            {"command": "proxy", "description": "WARP proxy on/off + status"},
            {"command": "rotate", "description": "Rotate WARP exit IP"},
            {"command": "sethome", "description": "Set home channel for cron"},
            {"command": "platforms", "description": "Show gateway status"},
            {"command": "restart", "description": "Restart the gateway"},
            {"command": "compact", "description": "Compact context (native)"},
            {"command": "commands", "description": "List OpenCode commands"},
            {"command": "run", "description": "Run an OpenCode command"},
            {"command": "skills", "description": "List skills"},
            {"command": "diff", "description": "Show session diff"},
            {"command": "export", "description": "Export session as file"},
            {"command": "review", "description": "Review changes (native)"},
            {"command": "init", "description": "Guided AGENTS.md setup"},
            {"command": "footer", "description": "Toggle reply footer"},
            {"command": "cron", "description": "Scheduled tasks"},
            {"command": "limits", "description": "Rate-limit status"},
            {"command": "goal", "description": "Standing goal (auto-continues)"},
            {"command": "loop", "description": "Repeat prompt in session"},
            {"command": "context", "description": "Context window gauge"},
            {"command": "queue", "description": "Queue prompt next"},
            {"command": "branch", "description": "Fork session here"},
            {"command": "plan", "description": "Plan without executing"},
        ],
    },
    "gateway": {
        "max_concurrent_updates": 8,
        "webhook": {"enabled": False, "url": "", "secret": "", "port": 8443},
        "routing": {
            "default_profile": "default",
            "rules": [],  # [{"chat_id": "-100...", "thread_id": "5", "profile": "work"}]
        },
        "profiles": {
            "default": {
                "workspace": os.path.join(os.path.expanduser("~"),
                                         "oc-workspace"),
                "model": "",
                "agent": "",
                "auto_approve": True,
                "timeout_sec": 900,
            },
        },
    },
    "proxy": {"enabled": False, "url": "http://127.0.0.1:8118",
              "no_proxy": "localhost,127.0.0.1,::1"},
    "stt": {"enabled": True, "provider": "auto", "model": "whisper-large-v3-turbo",
            "language": ""},
    "cron": {"enabled": True, "poll_sec": 30, "max_jobs": 50},
    "goals": {"max_turns": 20},
    "vision": {"fallback_model": "opencode/mimo-v2.6-flash-free"},
    "bot_loop_guard": {"enabled": True, "max_events": 20,
                       "window_seconds": 300, "cooldown_seconds": 600},
    "personalities": {
        "concise": "Answer concisely. No preamble, no restating the "
                   "question.",
        "sre": "You are a senior SRE: precise, ops-minded, and you verify "
               "before anything destructive.",
    },
    "warp_cli": "warp-cli",
    "opencode_bin": "opencode",
    "poll_timeout": 30,
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def deep_update(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)
        else:
            dst[k] = v


def resolve_env_strings(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                obj[k] = os.environ.get(v[2:-1], "")
            else:
                resolve_env_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            resolve_env_strings(v)


def _id_list(values) -> list:
    out = []
    for v in values:
        s = str(v).strip()
        if s.lstrip("-").isdigit():
            out.append(int(s))
    return out


def load_cfg() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if os.path.exists(CFG_PATH):
        try:
            with open(CFG_PATH) as f:
                deep_update(cfg, json.load(f))
        except Exception as e:  # noqa: BLE001
            log(f"config.json rusak ({e}); pakai default")
    tel = cfg["telegram"]
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        tel["bot_token"] = os.environ["TELEGRAM_BOT_TOKEN"]
    if os.environ.get("TELEGRAM_HOME_CHANNEL"):
        tel["home_channel"] = os.environ["TELEGRAM_HOME_CHANNEL"]
    if os.environ.get("TELEGRAM_PROXY"):
        tel["proxy_url"] = os.environ["TELEGRAM_PROXY"]
    for key, env in (("allowed_users", "TELEGRAM_ALLOWED_USERS"),
                     ("allowed_chats", "TELEGRAM_ALLOWED_CHATS"),
                     ("group_allowed_chats",
                      "TELEGRAM_GROUP_ALLOWED_CHATS"),
                     ("group_allow_from",
                      "TELEGRAM_GROUP_ALLOWED_USERS")):
        if os.environ.get(env):
            tel[key] = [s.strip() for s in os.environ[env].split(",")
                        if s.strip()]
    for key, env in (("cron_thread_id", "TELEGRAM_CRON_THREAD_ID"),
                     ("notifications", "HERMES_TELEGRAM_NOTIFICATIONS")):
        if os.environ.get(env):
            tel[key] = os.environ[env]
    resolve_env_strings(cfg)
    tel["allowed_users"] = _id_list(tel["allowed_users"])
    tel["allowed_chats"] = _id_list(tel["allowed_chats"])
    tel["group_allowed_chats"] = _id_list(tel["group_allowed_chats"])
    tel["group_allow_from"] = _id_list(tel["group_allow_from"])
    if os.environ.get("TELEGRAM_HOME_CHANNEL"):
        tel["home_channel"] = os.environ["TELEGRAM_HOME_CHANNEL"]

    if not tel["bot_token"]:
        log("FATAL: bot token belum diisi (config.json telegram.bot_token "
            "atau env TELEGRAM_BOT_TOKEN)")
        sys.exit(1)
    if not tel["allowed_users"]:
        log("PERINGATAN: allowed_users kosong -> semua pesan ditolak.")
    return cfg


def save_cfg(cfg: dict) -> None:
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CFG_PATH)
    try:
        os.chmod(CFG_PATH, 0o600)
    except OSError:
        pass


class State:
    """state.json: sesi per (chat,thread), model override, home channel."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data = {"sessions": {}, "models": {}, "agents": {},
                     "titles": {}, "home_channel": "", "last_prompts": {},
                     "personas": {}, "reasoning": {}, "pending": {},
                     "named": {}, "usage": {}, "observed": {}, "cron": {},
                     "cron_seq": 0}
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    self.data.update(json.load(f))
            except Exception:  # noqa: BLE001
                pass

    def save(self) -> None:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, STATE_PATH)

    def get_session(self, key: str):
        with self.lock:
            return self.data["sessions"].get(key)

    def set_session(self, key: str, sid: str) -> None:
        with self.lock:
            self.data["sessions"][key] = sid
            self.save()

    def clear_session(self, key: str) -> None:
        with self.lock:
            self.data["sessions"].pop(key, None)
            self.save()

    def list_sessions(self):
        with self.lock:
            return dict(self.data["sessions"])

    def get_model(self, key: str):
        with self.lock:
            return self.data["models"].get(key, "")

    def set_model(self, key: str, model: str) -> None:
        with self.lock:
            self.data["models"][key] = model
            self.save()

    def get_agent(self, key: str):
        with self.lock:
            return self.data.get("agents", {}).get(key, "")

    def set_agent(self, key: str, agent: str) -> None:
        with self.lock:
            self.data.setdefault("agents", {})[key] = agent
            self.save()

    def get_title(self, key: str):
        with self.lock:
            return self.data.get("titles", {}).get(key, "")

    def set_title(self, key: str, title: str) -> None:
        with self.lock:
            self.data.setdefault("titles", {})[key] = title
            self.save()

    def get_last_prompt(self, key: str):
        with self.lock:
            return self.data.get("last_prompts", {}).get(key)

    def set_last_prompt(self, key: str, prompt: str) -> None:
        with self.lock:
            self.data.setdefault("last_prompts", {})[key] = prompt
            self.save()

    def get_persona(self, key: str):
        with self.lock:
            return self.data.get("personas", {}).get(key, "")

    def set_persona(self, key: str, text: str) -> None:
        with self.lock:
            self.data.setdefault("personas", {})[key] = text
            self.save()

    def get_reasoning(self, key: str) -> bool:
        with self.lock:
            return bool(self.data.get("reasoning", {}).get(key))

    def set_reasoning(self, key: str, on: bool) -> None:
        with self.lock:
            self.data.setdefault("reasoning", {})[key] = on
            self.save()

    def get_pending(self, key: str):
        with self.lock:
            return self.data.get("pending", {}).get(key)

    def set_pending(self, key: str, prompt) -> None:
        with self.lock:
            self.data.setdefault("pending", {})[key] = prompt
            self.save()

    def clear_pending(self, key: str) -> None:
        with self.lock:
            self.data.get("pending", {}).pop(key, None)
            self.save()

    def set_named(self, name: str, key: str, sid: str) -> None:
        with self.lock:
            self.data.setdefault("named", {})[f"{key}:{name}"] = sid
            self.save()

    def get_named(self, name: str, key: str):
        with self.lock:
            return self.data.get("named", {}).get(f"{key}:{name}")

    def list_named(self, key: str):
        with self.lock:
            pre = f"{key}:"
            return {k[len(pre):]: v for k, v in
                    self.data.get("named", {}).items()
                    if k.startswith(pre)}

    def add_usage(self, key: str, tin: int, tout: int) -> None:
        with self.lock:
            u = self.data.setdefault("usage", {}).setdefault(
                key, {"input": 0, "output": 0})
            u["input"] += tin
            u["output"] += tout
            self.save()

    def get_usage(self, key: str):
        with self.lock:
            return self.data.get("usage", {}).get(key, {"input": 0, "output": 0})

    def reset_usage(self, key: str) -> None:
        with self.lock:
            self.data.setdefault("usage", {})[key] = {"input": 0, "output": 0}
            self.save()

    # -- quota hits per model (rate-limit visibility via /limits) ----------
    def add_quota(self, model: str) -> None:
        with self.lock:
            q = self.data.setdefault("quota", {}).setdefault(
                model or "(sesi)", {"hits": 0, "last": 0})
            q["hits"] += 1
            q["last"] = time.time()
            self.save()

    def get_quota(self) -> dict:
        with self.lock:
            return dict(self.data.get("quota", {}))

    def get_home(self):
        with self.lock:
            return self.data.get("home_channel") or \
                CFG["telegram"].get("home_channel") or ""

    def set_home(self, channel) -> None:
        with self.lock:
            self.data["home_channel"] = str(channel)
            self.save()

    def set_restart_notice(self, chat_id, thread_id) -> None:
        with self.lock:
            self.data["restart_notice"] = {
                "chat_id": chat_id, "thread_id": thread_id}
            self.save()

    def pop_restart_notice(self):
        with self.lock:
            n = self.data.pop("restart_notice", None)
            if n is not None:
                self.save()
            return n

    # -- goals ala Hermes (Ralph loop per sesi) ---------------------------
    def get_goal(self, key: str):
        with self.lock:
            return self.data.get("goals", {}).get(key)

    def set_goal(self, key: str, text: str, max_turns: int) -> None:
        with self.lock:
            self.data.setdefault("goals", {})[key] = {
                "text": text, "status": "active", "turns_used": 0,
                "max_turns": max_turns, "subgoals": []}
            self.save()

    def update_goal(self, key: str, **kw) -> None:
        with self.lock:
            g = self.data.get("goals", {}).get(key)
            if g:
                g.update(kw)
                self.save()

    def clear_goal(self, key: str) -> bool:
        with self.lock:
            if key in self.data.get("goals", {}):
                del self.data["goals"][key]
                self.save()
                return True
            return False

    def add_subgoal(self, key: str, text: str) -> bool:
        with self.lock:
            g = self.data.get("goals", {}).get(key)
            if not g:
                return False
            g.setdefault("subgoals", []).append(text)
            self.save()
            return True

    def clear_subgoals(self, key: str) -> bool:
        with self.lock:
            g = self.data.get("goals", {}).get(key)
            if not g:
                return False
            g["subgoals"] = []
            self.save()
            return True

    def remove_subgoal(self, key: str, idx: int) -> bool:
        with self.lock:
            g = self.data.get("goals", {}).get(key)
            subs = (g or {}).get("subgoals", [])
            if not g or not (1 <= idx <= len(subs)):
                return False
            subs.pop(idx - 1)
            self.save()
            return True

    # -- aktivitas sesi (idle gate heartbeat) + steer note -----------------
    def note_activity(self, key: str) -> None:
        with self.lock:
            self.data.setdefault("activity", {})[key] = time.time()
            self.save()

    def last_activity(self, key: str) -> float:
        with self.lock:
            return float(self.data.get("activity", {}).get(key, 0) or 0)

    def set_steer(self, key: str, text: str) -> None:
        with self.lock:
            notes = self.data.setdefault("steer", {}).setdefault(key, [])
            notes.append(text[:500])
            del notes[:-3]
            self.save()

    def consume_steer(self, key: str) -> list:
        with self.lock:
            notes = self.data.setdefault("steer", {}).pop(key, [])
            if notes:
                self.save()
            return notes

    # -- observed group context (unmentioned messages) ---------------------
    def push_observed(self, key: str, line: str, cap: int = 20) -> None:
        with self.lock:
            buf = self.data.setdefault("observed", {}).setdefault(key, [])
            buf.append(line[:500])
            del buf[:-cap]
            self.save()

    def consume_observed(self, key: str) -> list:
        with self.lock:
            buf = self.data.setdefault("observed", {}).pop(key, [])
            if buf:
                self.save()
            return buf

    # -- cron jobs ----------------------------------------------------------
    def cron_add(self, job: dict) -> str:
        with self.lock:
            self.data.setdefault("cron", {})
            seq = int(self.data.get("cron_seq", 0)) + 1
            self.data["cron_seq"] = seq
            jid = f"c{seq}"
            job["id"] = jid
            self.data["cron"][jid] = job
            self.save()
            return jid

    def cron_list(self) -> dict:
        with self.lock:
            return dict(self.data.get("cron", {}))

    def cron_get(self, jid: str):
        with self.lock:
            return self.data.get("cron", {}).get(jid)

    def cron_rm(self, jid: str) -> bool:
        with self.lock:
            if jid in self.data.get("cron", {}):
                del self.data["cron"][jid]
                self.save()
                return True
            return False

    def cron_set_enabled(self, jid: str, on: bool) -> bool:
        with self.lock:
            j = self.data.get("cron", {}).get(jid)
            if not j:
                return False
            j["enabled"] = on
            self.save()
            return True

    def cron_touch(self, jid: str, ts: float) -> None:
        with self.lock:
            j = self.data.get("cron", {}).get(jid)
            if j:
                j["last_run"] = ts
                self.save()


def load_dotenv() -> None:
    """Muat BASE/.env (KEY=VALUE, dukung # komentar & quotes) ke os.environ.

    Tak menimpa env yang sudah ada (systemd EnvironmentFile / export manual
    tetap menang). Dipanggil sebelum load_cfg() agar token & ID bisa penuh
    dari .env — rahasia tak perlu hardcode di config.json.
    """
    path = os.path.join(BASE, ".env")
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if not k or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                    continue
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                if k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


load_dotenv()
CFG = load_cfg()
STATE = State()
RUNTIME = {"bot_id": 0, "bot_username": ""}  # diisi main()


def resolve_profile(chat_id, thread_id):
    best = None
    for r in CFG["gateway"]["routing"]["rules"]:
        cid = str(r.get("chat_id", "") or "")
        if cid and cid != str(chat_id):
            continue
        tid = str(r.get("thread_id", "") or "")
        if tid and tid != str(thread_id or ""):
            continue
        if best is None or (tid and not str(best.get("thread_id", "") or "")):
            best = r
    name = (best or {}).get(
        "profile", CFG["gateway"]["routing"]["default_profile"])
    profiles = CFG["gateway"]["profiles"]
    return name, profiles.get(name, profiles["default"])


def session_key(chat_id, thread_id) -> str:
    return f"{chat_id}:{thread_id or 'root'}"


# ----------------------------------------------------------------------------
# media & prompt


def esc(s) -> str:
    return _html.escape(str(s))
