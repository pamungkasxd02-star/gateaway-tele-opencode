#!/usr/bin/env python3
"""
OpenCode HTTP API executor untuk gateway.

Gateway pakai OpenCode server privat (spawn sendiri, bisa bawa env proxy WARP)
dan ngobrol pakai API aslinya — sama persis kayak Hermes ngobrol sama agent-nya:

    POST /api/session                 -> bikin sesi (bisa set model/lokasi)
    POST /api/session/{id}/prompt     -> kirim pesan
    GET  /api/session/{id}/message    -> polling isi percakapan (parts)
    POST /api/session/{id}/compact    -> compact asli
    POST /api/session/{id}/interrupt  -> stop
    POST /api/session/{id}/revert     -> undo (filesystem revert)
    POST /api/session/{id}/command    -> jalankan slash command OpenCode
    GET  /api/command                 -> daftar command OpenCode
    POST /api/session/{id}/model      -> ganti model
    POST /api/session/{id}/agent      -> ganti agent
    POST /api/session/{id}/fork       -> sesi cabang (buat /btw)
    POST /api/session/{id}/background -> background task
    GET  /api/permission/request      -> request approval yang nunggu
    POST /api/session/{id}/permission/{rid}/reply -> approve/deny
"""

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

HOST = "127.0.0.1"
PORT = 4097
BASE = f"http://{HOST}:{PORT}"
GW_DIR = os.path.dirname(os.path.abspath(__file__))
PW_FILE = os.path.join(GW_DIR, ".server_password")
PROXY_URL = "http://127.0.0.1:8118"
NO_PROXY = "localhost,127.0.0.1,::1"
OPENCODE = "opencode"
CWD = os.path.expanduser("~")


# ---------------------------------------------------------------------------
# server privat (dibawa gateway; bawa env proxy supaya trafik keluar lewat WARP)
# ---------------------------------------------------------------------------

def _password() -> str:
    if os.path.exists(PW_FILE):
        return open(PW_FILE).read().strip()
    import secrets
    pw = "ocgw" + secrets.token_hex(12)
    with open(PW_FILE, "w") as f:
        f.write(pw)
    os.chmod(PW_FILE, 0o600)
    return pw


def _server_env(proxy_on: bool) -> dict:
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        env.pop(k, None)
    if proxy_on:
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = env["ALL_PROXY"] = PROXY_URL
        env["NO_PROXY"] = NO_PROXY
    env["OPENCODE_PASSWORD"] = _password()
    return env


def server_up() -> bool:
    d = api("get", "/api/info", timeout=15)
    return d is not None and not is_err(d)


PID_FILE = os.path.join(GW_DIR, ".server_pid")


def _write_pid(pid: int) -> None:
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(pid))
    except OSError:
        pass


def _read_pid() -> int:
    try:
        return int(open(PID_FILE).read().strip())
    except Exception:  # noqa: BLE001
        return 0


def stop_server() -> None:
    pid = _read_pid()
    if pid:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    # fallback: bunuh sisa proses serve di port ini milik user ini
    try:
        r = subprocess.run(["pgrep", "-f",
                            f"opencode serve --hostname {HOST} --port {PORT}"],
                           capture_output=True, text=True, timeout=10)
        for line in (r.stdout or "").split():
            try:
                if int(line) != os.getpid():
                    os.kill(int(line), 15)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2)


def ensure_server(proxy_on: bool = True):
    """Hidupkan server privat kalau belum ada. Kembalikan True kalau siap."""
    if server_up():
        return True
    p = subprocess.Popen(
        [OPENCODE, "serve", "--hostname", HOST, "--port", str(PORT)],
        cwd=CWD, env=_server_env(proxy_on),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    _write_pid(p.pid)
    for _ in range(20):
        time.sleep(1)
        if server_up():
            return True
    return False


def restart_server(proxy_on: bool = True):
    """Restart server privat (dipakai /proxy on|off)."""
    stop_server()
    time.sleep(1)
    return ensure_server(proxy_on)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def _auth_header() -> dict:
    tok = base64.b64encode(f"opencode:{_password()}".encode()).decode()
    return {"Authorization": f"Basic {tok}",
            "Content-Type": "application/json"}


def api(method: str, path: str, body=None, timeout: int = 90):
    """HTTP langsung ke server privat (tanpa CLI: tanpa batas output 256KB,
    tanpa spawn proses per call). Kontrak tetap: data / True / __err."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=_auth_header(),
                                 method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            err = {}
        msg = (err.get("message") or "").strip()
        tag = (err.get("_tag") or "").strip()
        detail = f"{tag}: {msg}" if tag else (msg or f"HTTP {e.code}")
        return {"__err": detail[:300]}
    except TimeoutError:
        return {"__err": "timeout"}
    except Exception as e:  # noqa: BLE001
        return {"__err": str(e)[:300]}
    if not raw.strip():
        return True  # sukses tanpa body (delete/background/revert)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"__err": f"respons API rusak ({path})"}
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload  # sebagian endpoint (/api/info) tak bungkus data


def is_err(d) -> bool:
    return isinstance(d, dict) and "__err" in d


# ---------------------------------------------------------------------------
# sesi
# ---------------------------------------------------------------------------

def model_ref(model: str):
    """'opencode/ling-3.1-flash-free' -> {'providerID': 'opencode', ...}"""
    if not model:
        return None
    if "/" in model:
        provider, mid = model.split("/", 1)
        return {"providerID": provider, "id": mid}
    return {"id": model}


def create_session(workspace: str, model: str = "", title: str = "telegram",
                   agent: str = ""):
    body = {"title": title}
    if workspace:
        body["location"] = {"directory": workspace}
    ref = model_ref(model)
    if ref:
        body["model"] = ref
    if agent:
        body["agent"] = agent
    d = api("post", "/api/session", body)
    if is_err(d) or not isinstance(d, dict):
        return None
    return d.get("id")


def switch_model(sid: str, model: str):
    return api("post", f"/api/session/{sid}/model",
               {"model": model_ref(model)})


def switch_agent(sid: str, agent: str):
    return api("post", f"/api/session/{sid}/agent", {"agent": agent})


def fork_session(sid: str):
    d = api("post", f"/api/session/{sid}/fork", {})
    if isinstance(d, dict):
        return d.get("id") or d.get("sessionID")
    return None


def background(sid: str):
    return api("post", f"/api/session/{sid}/background")


def interrupt(sid: str):
    return api("post", f"/api/session/{sid}/interrupt")


def revert_clear(sid: str):
    return api("delete", f"/api/session/{sid}/revert")


def compact(sid: str):
    return api("post", f"/api/session/{sid}/compact", {})


def run_command(sid: str, name: str, text: str = ""):
    return api("post", f"/api/session/{sid}/command",
               {"name": name, "text": text})


def list_sessions(limit: int = 15, search: str = ""):
    path = f"/api/session?limit={limit}"
    if search:
        path += f"&search={search}"
    d = api("get", path)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("sessions") or d.get("data") or []
    return []


def delete_session(sid: str):
    return api("delete", f"/api/session/{sid}")


def messages(sid: str):
    d = api("get", f"/api/session/{sid}/message", timeout=120)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("messages") or d.get("data") or []
    return []


def session_info(sid: str):
    d = api("get", f"/api/session/{sid}")
    return d if isinstance(d, dict) else {}


def context_info(sid: str):
    d = api("get", f"/api/session/{sid}/context")
    return d if isinstance(d, dict) else {}


def pending_permissions():
    d = api("get", "/api/permission/request")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("requests") or d.get("data") or []
    return []


def reply_permission(sid: str, request_id: str, allow: bool):
    # coba beberapa bentuk body yang umum dipakai
    for body in ({"reply": "always" if allow else "reject"},
                 {"allow": allow},
                 {"approved": allow}):
        r = api("post",
                f"/api/session/{sid}/permission/{request_id}/reply",
                body)
        if not is_err(r):
            return r
    return None


def skill_list():
    d = api("get", "/api/skill")
    return d if isinstance(d, list) else (d or {}).get("skills", [])


def command_list():
    d = api("get", "/api/command")
    return d if isinstance(d, list) else (d or {}).get("commands", [])


def model_list():
    d = api("get", "/api/model")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("models") or d.get("data") or []
    return []


def model_limits():
    """{model_id: context_length} dari daftar model."""
    out = {}
    for m in model_list() or []:
        lim = (m.get("limit") or {})
        ctx = lim.get("context") or lim.get("context_length")
        if ctx:
            out[m.get("id") or m.get("modelID")] = ctx
    return out


def agent_list():
    d = api("get", "/api/agent")
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return d.get("agents") or d.get("data") or []
    return []


def export_session(sid: str, path: str):
    req = urllib.request.Request(
        BASE + f"/api/experimental/session/{sid}/export",
        headers=_auth_header(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            blob = r.read()
            if not blob:
                return False
            with open(path, "wb") as f:
                f.write(blob)
            return os.path.exists(path)
    except Exception:  # noqa: BLE001
        return False


def diff(sid: str):
    d = api("get", f"/api/session/{sid}/diff")
    return d if isinstance(d, (dict, list)) else {}


# ---------------------------------------------------------------------------
# turn: kirim prompt, polling message sampai selesai
# ---------------------------------------------------------------------------

class TurnState:
    def __init__(self):
        self.texts: list = []            # teks assistant (urut)
        self.tools: "dict" = {}          # part id -> (name, label, done)
        self.reasoning: list = []        # thinking (kalau model kasih plain)
        self.usage = {"input": 0, "output": 0, "reasoning": 0}
        self.last_input = 0              # token input call terakhir (konteks)
        self.error = ""
        self.done = False
        self.sid = ""


def _brief_scalar(inp: dict, keys: list) -> str:
    for k in keys:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().replace("\n", " ")[:100]
    return ""


def _part_label(part: dict) -> str:
    name = (part.get("name") or "").lower()
    state = part.get("state") or {}
    inp = state.get("input") or {}
    if not isinstance(inp, dict):
        inp = {}
    label = ""
    if name in ("bash", "shell", "terminal", "run", "execute",
                "execute_code"):
        label = _brief_scalar(inp, ["command", "script", "cmd", "code"])
    elif name in ("read", "view"):
        label = _brief_scalar(inp, ["filePath", "path", "file_path"])
    elif name in ("write", "edit", "patch", "create", "apply_patch"):
        label = _brief_scalar(inp, ["filePath", "path", "file_path",
                                    "diff", "content"])
    elif name in ("grep", "codesearch", "glob", "ls"):
        label = _brief_scalar(inp, ["pattern", "path", "query", "filePath"])
    elif name in ("webfetch", "fetch", "web_search", "search", "web",
                  "browser"):
        label = _brief_scalar(inp, ["url", "query", "prompt"])
    elif name in ("skill",):
        label = _brief_scalar(inp, ["name", "id"])
    elif name in ("task", "delegate", "subagent"):
        label = _brief_scalar(inp, ["description", "prompt", "subagent_type"])
    elif name in ("todowrite", "todoread", "todo"):
        label = _brief_scalar(inp, ["content", "todos"])
    if not label:
        for v in inp.values():
            if isinstance(v, str) and v.strip() and len(v.strip()) < 80:
                label = v.strip().replace("\n", " ")[:100]
                break
    if not label:
        label = name or "tool"
    return label


def parse_messages(msgs: list, after_time: float) -> TurnState:
    st = TurnState()
    if not isinstance(msgs, list):
        return st
    for m in msgs:
        try:
            if not isinstance(m, dict):
                continue
            t = m.get("type")
            tm = m.get("time")
            created = tm.get("created", 0) if isinstance(tm, dict) else 0
            if t == "idle":
                if isinstance(created, (int, float)) and created >= after_time:
                    st.done = True
                continue
            if t == "assistant" and isinstance(created, (int, float)) \
                    and created >= after_time:
                if m.get("error"):
                    err = m["error"]
                    st.error = ((err.get("message") if isinstance(err, dict)
                                 else str(err)) or str(err))[:400]
                tok = m.get("tokens")
                tok = tok if isinstance(tok, dict) else {}
                for k in ("input", "output", "reasoning"):
                    v = tok.get(k)
                    st.usage[k] += v if isinstance(v, int) else 0
                if isinstance(tok.get("input"), int):
                    st.last_input = tok["input"]   # occupancy call terakhir
                content = m.get("content")
                if not isinstance(content, list):
                    continue
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    pt = p.get("type")
                    if pt == "text":
                        txt = p.get("text")
                        if txt and txt not in st.texts:
                            st.texts.append(txt)
                    elif pt == "reasoning":
                        txt = p.get("text") or ""
                        if txt and txt not in st.reasoning:
                            st.reasoning.append(txt)
                    elif pt == "tool":
                        state = p.get("state")
                        state = state if isinstance(state, dict) else {}
                        st.tools[p.get("id") or p.get("name") or "tool"] = (
                            p.get("name") or "tool",
                            _part_label(p),
                            state.get("status") == "completed")
                    elif pt in ("step-finish", "step_finish"):
                        tok = p.get("tokens")
                        tok = tok if isinstance(tok, dict) else {}
                        for k in ("input", "output", "reasoning"):
                            v = tok.get(k)
                            st.usage[k] += v if isinstance(v, int) else 0
                if m.get("finish") in ("stop", "error", "abort", "max_tokens",
                                       "length", "end_turn"):
                    st.done = True
        except Exception:  # noqa: BLE001
            continue  # satu message aneh jangan bunuh seluruh turn
    return st


def run_turn(sid: str, prompt: str, on_update=None, timeout: int = 900,
             interval: float = 2.0, no_output_limit: int = 420,
             files: list = None):
    """Kirim prompt lalu polling sampai turn selesai. Balikin TurnState.

    Watchdog: diam total (tanpa teks/tool) lebih dari no_output_limit
    dianggap macet — stop nunggu, balikin error jelas (user tak staring
    "Thinking…" selamanya).
    """
    body = {"text": prompt}
    if files:
        body["files"] = files
    r = api("post", f"/api/session/{sid}/prompt", body, timeout=120)
    if is_err(r):
        st = TurnState()
        st.error = r.get("__err", "gagal kirim prompt")
        st.done = True
        return st
    tm = (r or {}).get("time")
    user_time = (tm.get("created", 0) if isinstance(tm, dict) else 0) or 0
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        time.sleep(interval)
        st = parse_messages(messages(sid), user_time)
        if on_update and st != last:
            last = st
            try:
                on_update(st)
            except Exception:  # noqa: BLE001
                pass  # render gagal jangan bunuh polling turn
        if st.done:
            return st
        if not st.texts and not st.tools \
                and time.time() - t0 > min(no_output_limit, timeout):
            st = parse_messages(messages(sid), user_time)
            if not st.texts and not st.tools and not st.done:
                st.error = (st.error or
                            f"model diam {no_output_limit}s tanpa output "
                            "(macet/lamban). Coba /retry atau /model lain.")
                st.done = True
                return st
    st = parse_messages(messages(sid), user_time)
    st.error = st.error or "timeout"
    st.done = True
    return st
