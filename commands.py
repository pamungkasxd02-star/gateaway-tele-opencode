#!/usr/bin/env python3
"""Semua command Telegram: menu/nav, callback tombol, Hermes-set, mirror CLI,
cron, dan dispatcher handle_command."""

import json
import os
import re
import subprocess
import threading
import time

import executor
from core import (CFG, RUNTIME, STATE, esc, log, resolve_profile, save_cfg,
                  session_key)
from pipeline import (_egress_ip, _parse_interval, _warp_cli, enqueue,
                      rotate_egress, run_agent)
from render import fmt_tokens
from tg import TG, edit_rich, kv_block, send_rich

def run_cli(args, cwd=None, timeout=60) -> str:
    """Jalankan opencode CLI, kembalikan stdout (dipotong)."""
    try:
        r = subprocess.run([CFG["opencode_bin"]] + args, cwd=cwd,
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() or "(kosong)"
    except Exception as e:  # noqa: BLE001
        return f"(gagal: {e})"


MENU_TEXT = "<b>Menu</b>\nPilih opsi di bawah."


KEYBOARD = {"keyboard": [
    [{"text": "🆕 New"}, {"text": "📊 Status"}, {"text": "🧠 Model"}],
    [{"text": "⏰ Cron"}, {"text": "🌐 Proxy"}, {"text": "❓ Help"}],
], "resize_keyboard": True, "is_persistent": True}

BUTTON_MAP = {
    "🆕 New": "/new",
    "📊 Status": "/status",
    "🧠 Model": "/model",
    "⏰ Cron": "/cron list",
    "🌐 Proxy": "/proxy",
    "❓ Help": "/help",
}


def send_keyboard(chat_id) -> None:
    TG.call("sendMessage", chat_id=chat_id,
            text="⌨️ Tombol cepat aktif — tap langsung jalan.\n"
                 "Catatan: selama keyboard ini terbuka, tombol Menu (☰) "
                 "disembunyikan Telegram. <code>/keyboard off</code> untuk "
                 "kembalikan tombol Menu.",
            parse_mode="HTML",
            reply_markup=json.dumps(KEYBOARD))


def hide_keyboard(chat_id) -> None:
    TG.call("sendMessage", chat_id=chat_id,
            text="⌨️ Tombol cepat dimatikan — tombol Menu (☰) kembali.",
            reply_markup=json.dumps({"remove_keyboard": True}))


MENU = {"inline_keyboard": [
    [{"text": "Models", "callback_data": "nav:models"},
     {"text": "Sessions", "callback_data": "nav:sessions"}],
    [{"text": "Agents", "callback_data": "nav:agents"},
     {"text": "Status", "callback_data": "nav:status"}],
    [{"text": "Cron", "callback_data": "nav:cron"},
     {"text": "Limits", "callback_data": "nav:limits"}],
    [{"text": "Stats", "callback_data": "nav:stats"},
     {"text": "MCP", "callback_data": "nav:mcp"}],
    [{"text": "Help", "callback_data": "nav:help"}],
]}


def nav_content(page: str, chat_id, thread_id):
    """Bangun (teks, keyboard) buat halaman menu."""
    key = session_key(chat_id, thread_id)
    name, prof = resolve_profile(chat_id, thread_id)

    if page == "models":
        out = run_cli(["models"])
        models = [l.strip() for l in out.splitlines() if l.strip()]
        cur = STATE.get_model(key) or prof.get("model") or "(default profil)"
        rows = [[{"text": f"▶️ {m}", "callback_data": f"model:{m}"}]
                for m in models[:10]]
        rows.append([{"text": "◀ Menu", "callback_data": "nav:menu"}])
        body = "\n".join(f"• <code>{esc(m)}</code>" for m in models)
        return (f"🧠 <b>Models</b>\nAktif: <code>{esc(cur)}</code>\n\n{body}",
                {"inline_keyboard": rows})

    if page == "agents":
        agents = prof.get("agent") and [prof["agent"]] or []
        found = []
        for p in (os.path.join(os.path.expanduser(prof.get("workspace")),
                               "opencode.json"),
                  os.path.expanduser("~/.config/opencode/opencode.json")):
            try:
                with open(p) as f:
                    cfg = json.load(f)
                found += [k for k in (cfg.get("agent") or {})]
            except Exception:  # noqa: BLE001
                pass
        all_agents = list(dict.fromkeys(["build", "plan"] + agents + found))
        cur = STATE.get_agent(key) or prof.get("agent") or "(default)"
        rows = [[{"text": f"▶️ {a}", "callback_data": f"agent:{a}"}]
                for a in all_agents[:10]]
        rows.append([{"text": "◀ Menu", "callback_data": "nav:menu"}])
        body = "\n".join(f"• <code>{esc(a)}</code>" for a in all_agents)
        return (f"👥 <b>Agents</b>\nAktif: <code>{esc(cur)}</code>\n\n{body}",
                {"inline_keyboard": rows})

    if page == "sessions":
        sess = executor.list_sessions(limit=20) or []
        rows = []
        lines = []
        for s in sess[:10]:
            sid_ = s.get("id", "")
            title = s.get("title") or sid_[:16]
            lines.append(f"{sid_}  {title}")
            rows.append([{"text": f"{title[:30]}",
                          "callback_data": f"use:{sid_}"}])
        rows.append([{"text": "◀ Menu", "callback_data": "nav:menu"}])
        cur = STATE.get_session(key) or "(belum ada)"
        body = "\n".join(lines) or "(belum ada sesi)"
        return ("<b>Sessions</b>\nAktif: <code>" + esc(cur) + "</code>\n"
                "<pre>" + esc(body[:1500]) + "</pre>\n"
                "Tap sesi di bawah buat lanjutkan.",
                {"inline_keyboard": rows})

    if page == "mcp":
        out = run_cli(["mcp", "list"])
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        return (f"🔌 <b>MCP Servers</b>\n<pre>{esc(out[:2000])}</pre>", kb)

    if page == "auth":
        out = run_cli(["auth", "list"])
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        return (f"🔑 <b>Auth</b>\n<pre>{esc(out[:2000])}</pre>", kb)

    if page == "stats":
        out = run_cli(["stats"])
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        return (f"📊 <b>Stats</b>\n<pre>{esc(out[:2500])}</pre>", kb)

    if page == "cron":
        jobs = STATE.cron_list()
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        if not jobs:
            return ("⏰ <b>Cron</b>\n(belum ada job)\n\n"
                    "<code>/cron add 30m ...</code> untuk tambah.", kb)
        lines = [f"{'✅' if j.get('enabled', True) else '⏸️'} "
                 f"<code>{jid}</code> [{esc(j.get('expr', ''))}] "
                 f"{esc((j.get('prompt') or '')[:50])}"
                 for jid, j in sorted(jobs.items())]
        return ("⏰ <b>Cron jobs</b>\n" + "<br>".join(lines)
                + "\n\n<code>/cron rm &lt;id&gt;</code>", kb)

    if page == "limits":
        quota = STATE.get_quota()
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        if not quota:
            return ("🚦 <b>Limits</b>\n(belum ada limit tercatat)\n\n"
                    "<code>/rotate</code> · <code>/model</code>", kb)
        rows = "\n".join(
            f"• <code>{esc(m.split('/')[-1][:24])}</code> — "
            f"{q['hits']}x" for m, q in sorted(
                quota.items(), key=lambda kv: -kv[1]["hits"])[:10])
        return (f"🚦 <b>Limits</b>\n{rows}\n\n<code>/rotate</code> · "
                "<code>/model</code>", kb)

    if page == "status":
        model = STATE.get_model(key) or prof.get("model") or "profile default"
        agent = STATE.get_agent(key) or prof.get("agent") or "default"
        proxy = ("on (" + CFG["proxy"]["url"] + ")"
                 if CFG["proxy"].get("enabled") else "off")
        kb = {"inline_keyboard": [
            [{"text": "Models", "callback_data": "nav:models"},
             {"text": "Sessions", "callback_data": "nav:sessions"}],
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        return ("<b>Status</b> · " + esc(name) + "\n" + kv_block([
            ("Session", STATE.get_session(key) or "—"),
            ("Model", model),
            ("Agent", agent),
            ("Workspace", prof.get("workspace")),
            ("Timeout", f"{prof.get('timeout_sec')}s"),
            ("Proxy", proxy),
        ]), kb)

    if page == "help":
        kb = {"inline_keyboard": [
            [{"text": "◀ Menu", "callback_data": "nav:menu"}]]}
        return (HELP_HTML, kb)

    # default / menu
    return (MENU_TEXT, MENU)


def handle_callback(q: dict) -> None:
    cbq_id = q.get("id")
    msg = q.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    thread_id = msg.get("message_thread_id")
    mid = msg.get("message_id")
    user = q.get("from") or {}
    if user.get("id") not in CFG["telegram"]["allowed_users"]:
        TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                text="Akses ditolak", show_alert=True)
        return
    data = q.get("data") or ""
    key = session_key(chat_id, thread_id)

    if data.startswith("nav:"):
        TG.call("answerCallbackQuery", callback_query_id=cbq_id)
        text, kb = nav_content(data.split(":", 1)[1], chat_id, thread_id)
        edit_rich(chat_id, mid, text, kb)
        return

    if data.startswith("model:"):
        STATE.set_model(key, data.split(":", 1)[1])
        TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                text="Model di-set")
        text, kb = nav_content("models", chat_id, thread_id)
        edit_rich(chat_id, mid, text, kb)
        return

    if data.startswith("agent:"):
        STATE.set_agent(key, data.split(":", 1)[1])
        TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                text="Agent di-set")
        text, kb = nav_content("agents", chat_id, thread_id)
        edit_rich(chat_id, mid, text, kb)
        return

    if data.startswith("use:"):
        STATE.set_session(key, data.split(":", 1)[1])
        TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                text="Sesi dipilih")
        text, kb = nav_content("sessions", chat_id, thread_id)
        edit_rich(chat_id, mid, text, kb)
        return

    if data.startswith("ea:"):
        # approval card ala Hermes: ea:1:<chat>:<thread> / ea:0:...
        try:
            _, verdict, cid, tid = data.split(":", 3)
            ekey = session_key(int(cid), None if tid in ("0", "root")
                               else int(tid))
        except (ValueError, TypeError):
            TG.call("answerCallbackQuery", callback_query_id=cbq_id)
            return
        pend = STATE.get_pending(ekey)
        STATE.clear_pending(ekey)
        if verdict == "1" and pend:
            TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                    text="Approved — running")
            edit_rich(chat_id, mid, "✅ <b>Approved</b> — running now.")
            tparam = None if tid in ("0", "root") else int(tid)
            if isinstance(pend, dict):
                pp, pf = pend.get("prompt", ""), pend.get("files")
                pr = pend.get("reply_to", 0) or 0
            else:
                pp, pf, pr = pend, None, 0
            enqueue(ekey, lambda p=pp, f=pf, r=pr: run_agent(
                ekey, int(cid), tparam, p, reply_to=r, files=f))
        else:
            TG.call("answerCallbackQuery", callback_query_id=cbq_id,
                    text="Denied")
            edit_rich(chat_id, mid, "🚫 <b>Denied</b> — nothing was run.")
        return

    TG.call("answerCallbackQuery", callback_query_id=cbq_id)


def handle_hermes(c: str, chat_id: int, thread_id, user_id: int,
                  args: list, msg_id: int = 0) -> bool:
    """Command set ala Hermes: /retry /undo /bg /btw /approve /whoami ..."""
    key = session_key(chat_id, thread_id)

    if c == "reset":
        STATE.clear_session(key)
        send_rich(chat_id, "New conversation started.")
        return True

    if c == "retry":
        last = STATE.get_last_prompt(key)
        if not last:
            send_rich(chat_id, "No previous message to retry.")
            return True
        send_rich(chat_id, "Retrying last message…")
        enqueue(key, lambda l=last: run_agent(key, chat_id, thread_id, l))
        return True

    if c == "undo":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi — kirim pesan dulu.")
            return True
        r = executor.revert_clear(sid)
        if executor.is_err(r):
            send_rich(chat_id, f"❌ undo gagal: {esc(r.get('__err', '')[:150])}")
        else:
            send_rich(chat_id, "✅ Undo — revert terakhir dibersihkan.")
        return True

    if c == "whoami":
        send_rich(chat_id, kv_block([
            ("User", user_id),
            ("Chat", chat_id),
            ("Thread", thread_id or "root"),
            ("Access", "admin"),
            ("Session", STATE.get_session(key) or "—"),
            ("Model", STATE.get_model(key) or "profile default"),
        ]))
        return True

    if c in ("approve", "deny"):
        pend = STATE.get_pending(key)
        if pend:
            STATE.clear_pending(key)
            if c == "deny":
                send_rich(chat_id, "Denied — nothing was run.")
                return True
            send_rich(chat_id, "Approved — running now.")
            if isinstance(pend, dict):
                pp, pf = pend.get("prompt", ""), pend.get("files")
                pr = pend.get("reply_to", 0) or 0
            else:
                pp, pf, pr = pend, None, 0
            enqueue(key, lambda p=pp, f=pf, r=pr: run_agent(
                key, chat_id, thread_id, p, reply_to=r, files=f))
            return True
        sid = STATE.get_session(key)
        reqs = executor.pending_permissions() or []
        mine = [r for r in reqs
                if not sid or str(r.get("sessionID")) == str(sid)] or reqs
        if not mine:
            send_rich(chat_id, "Nothing pending approval.")
            return True
        ok = c == "approve"
        done = 0
        for r in mine[:5]:
            rid = r.get("id") or r.get("requestID")
            rsid = r.get("sessionID") or sid
            if rid and executor.reply_permission(rsid, str(rid), ok):
                done += 1
        send_rich(chat_id, ("✅ Approved" if ok else "🚫 Denied")
                  + f" — {done} request diproses.")
        return True

    if c in ("compress", "compact"):
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi — kirim pesan dulu.")
            return True
        send_rich(chat_id, "Compacting context…")
        r = executor.compact(sid)
        if executor.is_err(r):
            send_rich(chat_id, f"❌ compact gagal: {esc(r.get('__err', '')[:150])}")
        else:
            send_rich(chat_id, "✅ Context compacted — riwayat diringkas, "
                               "fak penting dipertahankan.")
        return True

    if c in ("title", "rename"):
        if len(args) >= 2:
            name = " ".join(args[1:])
            STATE.set_title(key, name)
            sid = STATE.get_session(key)
            if sid:
                STATE.set_named(name, key, sid)
            send_rich(chat_id, f"Session title: <b>{esc(name)}</b>")
        else:
            send_rich(chat_id,
                      f"Title: <b>{esc(STATE.get_title(key) or '(none)')}</b>")
        return True

    if c == "resume" and len(args) >= 2:
        name = " ".join(args[1:])
        sid = STATE.get_named(name, key) or name
        STATE.set_session(key, sid)
        STATE.set_title(key, name if STATE.get_named(name, key) else
                        STATE.get_title(key))
        send_rich(chat_id, f"Resumed: <code>{esc(sid)}</code>")
        return True

    if c == "reasoning":
        if len(args) >= 2 and args[1].lower() in ("on", "show"):
            STATE.set_reasoning(key, True)
            send_rich(chat_id, "Reasoning display: <b>on</b>")
        elif len(args) >= 2 and args[1].lower() in ("off", "hide"):
            STATE.set_reasoning(key, False)
            send_rich(chat_id, "Reasoning display: <b>off</b>")
        else:
            on = STATE.get_reasoning(key)
            send_rich(chat_id, f"Reasoning display: <b>{on}</b>\n"
                               "<code>/reasoning on</code> · "
                               "<code>/reasoning off</code>")
        return True

    if c == "personality":
        personas = CFG.get("personalities", {})
        if len(args) < 2:
            cur = STATE.get_persona(key)
            names = ", ".join(f"<code>{esc(n)}</code>"
                              for n in personas) or "(none configured)"
            send_rich(chat_id,
                      f"Personality: {esc(cur[:80]) if cur else '(default)'}\n"
                      f"Available: {names}\n"
                      "<code>/none</code> to reset")
        elif args[1].lower() in ("none", "reset", "off"):
            STATE.set_persona(key, "")
            send_rich(chat_id, "Personality reset to default.")
        else:
            name = args[1]
            text = personas.get(name)
            if not text:
                send_rich(chat_id, f"Unknown personality: {esc(name)}")
                return True
            STATE.set_persona(key, text)
            send_rich(chat_id, f"Personality: <b>{esc(name)}</b>")
        return True

    if c == "usage":
        u = STATE.get_usage(key)
        rows = [("Tokens (chat)", f"{fmt_tokens(u['input'])} in / "
                                 f"{fmt_tokens(u['output'])} out")]
        sid = STATE.get_session(key)
        if sid:
            info = executor.session_info(sid) or {}
            tok = info.get("tokens") or {}
            if tok:
                rows.append(("Input", fmt_tokens(tok.get("input", 0))))
                rows.append(("Output", fmt_tokens(tok.get("output", 0))))
                rows.append(("Reasoning", fmt_tokens(tok.get("reasoning", 0))))
            for k, v in list(info.items())[:6]:
                if k in ("tokens", "id", "time"):
                    continue
                if isinstance(v, (int, float, str)) and len(str(v)) < 40:
                    rows.append((k, v))
        send_rich(chat_id, "<b>Usage</b>\n" + kv_block(rows))
        return True

    if c == "insights":
        # alias jujur: sama kayak /stats (satu perilaku, tak dobel)
        text, kb = nav_content("stats", chat_id, thread_id)
        send_rich(chat_id, text, kb)
        return True

    if c == "bg" and len(args) > 1:
        prompt = " ".join(args[1:])
        sid = STATE.get_session(key)
        if sid:
            executor.background(sid)
        send_rich(chat_id,
                  f"🔄 Background task started: “{esc(prompt[:70])}”\n"
                  "Hasilnya masuk ke chat ini lagi kalau selesai.")
        threading.Thread(
            target=lambda: run_agent(key, chat_id, thread_id, prompt,
                                     mode="bg", reply_to=msg_id),
            daemon=True).start()
        return True

    if c == "btw" and len(args) > 1:
        q = " ".join(args[1:])
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi — kirim pesan dulu.")
            return True
        send_rich(chat_id, "💬 Side question diterima…")

        def _btw():
            fk = executor.fork_session(sid)
            target = fk or sid
            st = executor.run_turn(target, q, timeout=600)
            txt = "\n".join(st.texts).strip() or (st.error or "(no output)")
            send_rich(chat_id, f"💬 <b>Side answer</b>\n{esc(txt[:3300])}")
            if fk:
                executor.delete_session(fk)
        threading.Thread(target=_btw, daemon=True).start()
        return True

    if c == "platform":
        # alias: /platform list|status == /platforms (satu output, tak dobel)
        bu = RUNTIME["bot_username"]
        send_rich(chat_id,
                  "🔌 <b>Platform</b>\n"
                  f"• telegram: ✅ @{esc(bu or '?')}\n"
                  f"• polling: <b>{'OFF' if CFG['gateway']['webhook']['enabled'] else 'ON'}</b>\n"
                  f"• webhook: <b>{'ON' if CFG['gateway']['webhook']['enabled'] else 'OFF'}</b>")
        return True

    if c in ("reload-mcp", "reloadmcp"):
        out = run_cli(["mcp", "list"])
        send_rich(chat_id, f"🔌 <b>MCP servers</b>\n<pre>{esc(out[:1500])}</pre>\n"
                           "MCP dimuat saat server start — "
                           "<code>/restart</code> untuk reload penuh.")
        return True

    if c in ("commands", "opencode"):
        cmds = executor.command_list() or []
        if not cmds:
            send_rich(chat_id, "(tidak ada command terdaftar)")
            return True
        lines = []
        for cm in cmds[:40]:
            nm = cm.get("name") or cm.get("id") or "?"
            desc = (cm.get("description") or "")[:46]
            lines.append(f"/{nm}  {desc}")
        send_rich(chat_id, "<b>OpenCode commands</b>\n<pre>"
                  + esc("\n".join(lines)) + "</pre>\n"
                  "Jalankan: <code>/run &lt;nama&gt; [arg]</code>")
        return True

    if c == "run" and len(args) >= 2:
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi.")
            return True
        name = args[1]
        rest = " ".join(args[2:])
        send_rich(chat_id, f"Menjalankan <code>/{esc(name)}</code> …")
        r = executor.run_command(sid, name, rest)
        if executor.is_err(r):
            send_rich(chat_id, f"❌ gagal: {esc(r.get('__err', '')[:150])}")
        else:
            send_rich(chat_id, "✅ Dijalankan.")
        return True

    if c == "skills":
        sk = executor.skill_list() or []
        if not sk:
            send_rich(chat_id, "(belum ada skill terpasang)")
            return True
        lines = [f"• {s.get('name') or s.get('id')} — "
                 f"{(s.get('description') or '')[:50]}" for s in sk[:30]]
        send_rich(chat_id, "<b>Skills</b>\n" + esc("\n".join(lines)))
        return True

    if c == "diff":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi.")
            return True
        d = executor.diff(sid) or {}
        body = json.dumps(d)[:1800] if d else "(tidak ada perubahan)"
        send_rich(chat_id, "<b>Diff</b>\n<pre>" + esc(body) + "</pre>")
        return True

    if c == "export":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi.")
            return True
        path = os.path.join("/tmp", f"opencode-session-{sid[:12]}.json")
        if executor.export_session(sid, path):
            TG.send_media(chat_id, path, "document")
        else:
            send_rich(chat_id, "❌ export gagal.")
        return True

    if c == "update":
        send_rich(chat_id, "Checking for updates…")

        def _upd():
            out = run_cli(["upgrade"], timeout=300)
            send_rich(chat_id, f"<pre>{esc(out[:1500])}</pre>")
        threading.Thread(target=_upd, daemon=True).start()
        return True

    return False


def handle_extra(c: str, chat_id: int, thread_id, user_id: int,
                 args: list, msg_id: int = 0) -> bool:
    """Command tambahan (mirror OpenCode CLI). True kalau sudah ditangani."""
    key = session_key(chat_id, thread_id)

    if c == "sessions" and len(args) > 1:
        q = " ".join(args[1:]).strip()
        low = q.lower()
        if low in ("all", "search") or low.startswith("search "):
            q = "" if low == "all" else q[7:]
        name, prof = resolve_profile(chat_id, thread_id)
        ws = os.path.expanduser(prof.get("workspace"))
        os.makedirs(ws, exist_ok=True)
        out = run_cli(["session", "list"], cwd=ws)
        lines = [l for l in out.splitlines() if l.startswith("ses_")]
        if q:
            lines = [l for l in lines if q.lower() in l.lower()][:8]
        else:
            lines = lines[:8]
        rows = []
        for l in lines:
            parts = l.split("\t")
            title = parts[1] if len(parts) > 1 else parts[0][:16]
            rows.append([{"text": f"{title[:30]}",
                          "callback_data": f"use:{parts[0]}"}])
        rows.append([{"text": "◀ Menu", "callback_data": "nav:menu"}])
        body = "\n".join(lines) or "(no sessions)"
        send_rich(chat_id,
                  f"<b>Sessions</b>{' matching ' + esc(q) if q else ''}\n"
                  f"<pre>{esc(body[:2000])}</pre>\n"
                  "Tap one to switch.",
                  {"inline_keyboard": rows})
        return True

    if c == "menu":
        send_rich(chat_id, MENU_TEXT, MENU)
        return True

    if c in ("models", "agents", "sessions", "mcp", "auth", "stats",
             "usage", "status", "help"):
        page = {"usage": "stats"}.get(c, c)
        text, kb = nav_content(page, chat_id, thread_id)
        send_rich(chat_id, text, kb)
        return True

    if c == "model":
        name, prof = resolve_profile(chat_id, thread_id)
        if len(args) < 2:
            cur = STATE.get_model(key) or prof.get("model") or "(default)"
            send_rich(chat_id,
                      f"Model sekarang: <code>{esc(cur)}</code>\n"
                      "Ganti: <code>/model provider/model</code> atau /models")
        elif args[1].lower() == "reset":
            STATE.set_model(key, "")
            send_rich(chat_id, "✅ Balik ke model default profil.")
        else:
            STATE.set_model(key, args[1])
            send_rich(chat_id, f"✅ Model: <code>{esc(args[1])}</code>")
        return True

    if c == "agent":
        name, prof = resolve_profile(chat_id, thread_id)
        if len(args) < 2:
            cur = STATE.get_agent(key) or prof.get("agent") or "(default)"
            send_rich(chat_id,
                      f"Agent sekarang: <code>{esc(cur)}</code>\n"
                      "Ganti: <code>/agent build</code> atau /agents")
        elif args[1].lower() == "reset":
            STATE.set_agent(key, "")
            send_rich(chat_id, "✅ Balik ke agent default profil.")
        else:
            STATE.set_agent(key, args[1])
            send_rich(chat_id, f"✅ Agent: <code>{esc(args[1])}</code>")
        return True

    if c == "session":
        if len(args) >= 2:
            STATE.set_session(key, args[1])
            send_rich(chat_id, f"✅ Sesi aktif: <code>{esc(args[1])}</code>")
        else:
            send_rich(chat_id,
                      f"Sesi aktif: <code>"
                      f"{esc(STATE.get_session(key) or '(belum ada)')}</code>\n"
                      "Set: <code>/session ses_xxx</code> atau /sessions")
        return True

    if c == "plugins":
        out = run_cli(["plugin", "list"])
        send_rich(chat_id, f"🧩 <b>Plugins</b>\n<pre>{esc(out[:2000])}</pre>")
        return True

    if c == "rename" and len(args) >= 2:
        STATE.set_title(key, " ".join(args[1:]))
        send_rich(chat_id, f"✅ Judul sesi berikutnya: "
                           f"<b>{esc(' '.join(args[1:]))}</b>")
        return True

    if c == "init":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi — kirim pesan dulu.")
            return True
        send_rich(chat_id, "🛠️ Menjalankan init project (native)…")
        r = executor.run_command(sid, "init")
        send_rich(chat_id, "❌ init gagal: "
                  + esc(r.get("__err", "")[:150]) if executor.is_err(r)
                  else "✅ init dijalankan — ikuti panduan agent.")
        return True

    if c == "review":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Belum ada sesi.")
            return True
        target = args[1] if len(args) > 1 else ""
        send_rich(chat_id, "🔎 Review changes (native)…")
        r = executor.run_command(sid, "review", target)
        send_rich(chat_id, "❌ review gagal: "
                  + esc(r.get("__err", "")[:150]) if executor.is_err(r)
                  else "✅ review dijalankan — hasilnya dari agent.")
        return True

    if handle_hermes(c, chat_id, thread_id, user_id, args, msg_id):
        return True

    return False


HELP_HTML = (
    "<b>OpenCode Gateway</b>\n\n"
    "Send any message — it runs on the server and the reply comes back "
    "here. Voice notes, photos and files are forwarded to the agent; "
    "files the agent makes are attached back automatically.\n\n"
    "<b>Session</b>\n"
    "<code>/new</code> (= <code>/reset</code>) — new conversation\n"
    "<code>/retry</code> — run the last message again\n"
    "<code>/undo</code> — remove the last exchange\n"
    "<code>/compress</code> (= <code>/compact</code>) — compress context\n"
    "<code>/title [name]</code> (= <code>/rename</code>) — set title\n"
    "<code>/resume [name]</code> — resume a named session\n"
    "<code>/sessions</code> — list/switch · <code>/session id</code> — jump\n"
    "<code>/stop</code> — stop the running agent\n"
    "<code>/bg &lt;prompt&gt;</code> — background task\n"
    "<code>/btw &lt;question&gt;</code> — side question\n"
    "<code>/branch [name]</code> — fork session here\n\n"
    "<b>Model</b>\n"
    "<code>/model [provider:model]</code> — show or change model\n"
    "<code>/models</code> · <code>/agents</code> · <code>/agent [name]</code>\n"
    "<code>/personality [name]</code> · <code>/reasoning on|off</code>\n\n"
    "<b>Goals & loops</b>\n"
    "<code>/goal teks</code> — standing goal (auto-lanjut sampai done)\n"
    "<code>/goal status|pause|resume|clear</code> · "
    "<code>/subgoal ...</code>\n"
    "<code>/loop 5m cek deploy [--times N]</code> · "
    "<code>/loop status|stop id</code>\n"
    "<code>/heartbeat every 5m ...</code> — hanya saat idle\n"
    "<code>/queue prompt</code> — antre giliran berikut\n"
    "<code>/steer catatan</code> — arahkan turn berikut\n"
    "<code>/plan tugas</code> — tulis rencana, tanpa eksekusi\n\n"
    "<b>Info</b>\n"
    "<code>/status</code> · <code>/usage</code> · <code>/context</code> · "
    "<code>/whoami</code> · <code>/stats</code> (= <code>/insights</code>)\n"
    "<code>/mcp</code> (+<code>/reload-mcp</code>) · <code>/auth</code> · "
    "<code>/plugins</code> · <code>/update</code> · <code>/config</code>\n"
    "<code>/commands</code> · <code>/run nama</code> · "
    "<code>/skills</code> · <code>/diff</code> · <code>/export</code>\n"
    "<code>/init</code> · <code>/review [target]</code>\n\n"
    "<b>Gateway</b>\n"
    "<code>/sethome</code> · <code>/platforms</code> (= <code>/platform</code>)"
    " · <code>/menu</code> · <code>/keyboard</code>\n"
    "<code>/proxy on|off</code> (= <code>/egress</code> status) · "
    "<code>/rotate</code> · <code>/limits</code>\n"
    "<code>/cron list|add|rm|on|off</code> — scheduled tasks ke home\n"
    "<code>/approve</code> · <code>/deny</code> — dangerous command "
    "approval\n"
    "<code>/footer on|off</code> · <code>/restart</code> · "
    "<code>/help</code>\n\n"
    "Command lain yang diketik dijalankan sebagai skill agent. "
    "Only allowlisted users can use this bot."
)


def _cron_expr_error(expr: str):
    """Validasi expr cron. Kembalikan pesan salah, atau None kalau OK."""
    iv = _parse_interval(expr)
    if iv is not None:
        if iv < 60:
            return ("Interval minimal <b>1m</b> — pakai "
                    "<code>1m</code>, <code>30m</code>, <code>2h</code>, …")
        return None
    low = expr.strip().lower()
    if low.startswith("daily"):
        try:
            hh, mm = [int(x) for x in expr.split(None, 1)[1].split(":")]
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return None
        except Exception:  # noqa: BLE001
            pass
        return ("Format: <code>daily HH:MM</code>, mis. "
                "<code>daily 07:00</code>.")
    parts = expr.split()
    if len(parts) == 5 and all(
            re.fullmatch(r"[\d,*/-]+", p) for p in parts):
        try:
            mn, hr = parts[0], parts[1]
            ok_m = mn == "*" or all(
                0 <= int(x) <= 59
                for x in re.split(r"[,/-]", mn) if x not in ("", "*"))
            nums_h = [x for x in re.split(r"[,/-]", hr)
                      if x not in ("", "*")]
            ok_h = hr == "*" or all(
                0 <= int(x) <= 23 for x in nums_h)
            if ok_m and ok_h:
                return None
        except ValueError:
            pass
        return ("Menit harus 0-59 dan jam 0-23, mis. "
                "<code>*/15 7-22 * * *</code>.")
    return ("Pakai <code>10s|5m|2h</code> (min 1m), "
            "<code>daily HH:MM</code>, atau cron "
            "<code>m h dom mon dow</code>.")


def handle_cron(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Cron ala Hermes: /cron add <expr> <prompt> | list | rm <id> | on/off."""
    jobs = STATE.cron_list()
    if len(args) < 2 or args[1].lower() in ("list", "ls"):
        if not jobs:
            send_rich(chat_id,
                      "<b>Cron</b>\n(belum ada job)\n\n"
                      "Tambah: <code>/cron add 30m prompt kamu</code>\n"
                      "Format: <code>1m|30m|2h|1d</code> (min 1m) · "
                      "<code>daily 07:00</code> · "
                      "<code>*/15 * * * *</code>\n"
                      "Hasil dikirim ke home channel "
                      "(<code>/sethome</code>).")
            return
        lines = []
        for jid, j in sorted(jobs.items()):
            st = "✅" if j.get("enabled", True) else "⏸️"
            lines.append(f"{st} <code>{jid}</code> [{esc(j.get('expr',''))}] "
                         f"{esc((j.get('prompt') or '')[:60])}")
        send_rich(chat_id, "<b>Cron jobs</b>\n" + "<br>".join(lines) +
                  "\n\n<code>/cron rm &lt;id&gt;</code> · "
                  "<code>/cron off &lt;id&gt;</code> · "
                  "<code>/cron on &lt;id&gt;</code>")
        return
    sub = args[1].lower()
    if sub == "add":
        if len(args) < 4:
            send_rich(chat_id,
                      "Pakai: <code>/cron add &lt;expr&gt; &lt;prompt&gt;</code>\n"
                      "Contoh: <code>/cron add 30m cek harga BTC</code>")
            return
        expr = args[2]
        prompt = " ".join(args[3:])
        # dukung cron 5-field yang mengandung spasi: coba gabung 5 token
        if _cron_expr_error(expr) and len(args) >= 8:
            cand = " ".join(args[2:7])
            if len(cand.split()) == 5 and not _cron_expr_error(cand):
                expr = cand
                prompt = " ".join(args[7:])
        err = _cron_expr_error(expr)
        if err:
            send_rich(chat_id,
                      f"Expr nggak valid: <code>{esc(expr)}</code>\n{err}")
            return
        if len(jobs) >= int(CFG.get("cron", {}).get("max_jobs", 50)):
            send_rich(chat_id, "❌ Kebanyakan job.")
            return
        jid = STATE.cron_add({"expr": expr, "prompt": prompt,
                              "chat_id": chat_id, "thread_id": thread_id,
                              "enabled": True, "last_run": 0,
                              "created_by": user_id})
        home = STATE.get_home()
        send_rich(chat_id,
                  f"✅ Cron <code>{jid}</code> [{esc(expr)}] aktif.\n"
                  f"Hasil → {'home channel' if home else 'chat ini'}.")
        return
    if sub in ("rm", "del", "remove") and len(args) >= 3:
        ok = STATE.cron_rm(args[2])
        send_rich(chat_id, "✅ Dihapus." if ok else "❌ ID nggak ketemu.")
        return
    if sub in ("on", "off") and len(args) >= 3:
        ok = STATE.cron_set_enabled(args[2], sub == "on")
        send_rich(chat_id, "✅ Diupdate." if ok else "❌ ID nggak ketemu.")
        return
    send_rich(chat_id,
              "Pakai: <code>/cron list</code> · "
              "<code>/cron add &lt;expr&gt; &lt;prompt&gt;</code> · "
              "<code>/cron rm &lt;id&gt;</code>")


def handle_goal(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Standing goal ala Hermes (Ralph loop): set/status/pause/resume/clear."""
    from pipeline import run_agent as _run
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    low = rest.lower()
    g = STATE.get_goal(key)

    def _status_text(gg) -> str:
        subs = gg.get("subgoals") or []
        max_t = gg.get("max_turns", 20)
        lines = [f"🎯 <b>Goal</b> [{esc(gg.get('status', '?'))}] "
                 f"({gg.get('turns_used', 0)}/{max_t} turns)",
                 f"<pre>{esc(gg.get('text', ''))}</pre>"]
        if subs:
            lines.append("Subgoals:\n" + "\n".join(
                f"{i}. {esc(s)}" for i, s in enumerate(subs, 1)))
        lines.append("<code>/goal pause|resume|clear</code> · "
                     "<code>/subgoal ...</code>")
        return "\n".join(lines)

    if not rest or low in ("status", "show"):
        send_rich(chat_id, _status_text(g) if g else
                  "(belum ada goal di sesi ini)\n"
                  "Set: <code>/goal perbaiki semua test sampai hijau</code>")
        return
    if low in ("pause", "stop"):
        if not g:
            send_rich(chat_id, "(belum ada goal)")
            return
        STATE.update_goal(key, status="paused")
        send_rich(chat_id, "⏸ <b>Goal paused.</b>")
        return
    if low in ("resume", "continue", "unpause"):
        if not g:
            send_rich(chat_id, "(belum ada goal)")
            return
        max_t = int(CFG.get("goals", {}).get("max_turns", 20))
        STATE.update_goal(key, status="active", turns_used=0)
        send_rich(chat_id, "▶️ <b>Goal resumed</b> "
                           f"(budget reset {max_t}).")
        enqueue(key, lambda: _run(
            key, chat_id, thread_id,
            f"[Goal resumed] Standing goal: {g.get('text', '')}"))
        return
    if low in ("clear", "drop", "cancel"):
        send_rich(chat_id, "🗑 <b>Goal cleared.</b>"
                  if STATE.clear_goal(key) else "(belum ada goal)")
        return
    if low.split()[0] in ("pause", "status", "show", "resume", "continue",
                           "unpause", "clear", "drop", "cancel"):
        send_rich(chat_id, "Pakai: <code>/goal status|pause|resume|clear</code>\n"
                           "Teks bebas = goal baru. Awali <code>-- </code> "
                           "bila teks mulai dengan kata kontrol.")
        return
    if low.startswith("--"):
        rest = rest[2:].strip()
    max_t = int(CFG.get("goals", {}).get("max_turns", 20))
    STATE.set_goal(key, rest, max_t)
    send_rich(chat_id, f"⊙ <b>Goal set</b> ({max_t}-turn budget):\n"
                       f"<pre>{esc(rest[:800])}</pre>\n"
                       "Turn pertama jalan…")
    enqueue(key, lambda p=rest: _run(key, chat_id, thread_id, p))


def handle_subgoal(chat_id: int, thread_id, user_id: int, args: list) -> None:
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    low = rest.lower()
    g = STATE.get_goal(key)
    if not rest:
        subs = (g or {}).get("subgoals", []) if g else []
        send_rich(chat_id, "Subgoals:\n" + "\n".join(
            f"{i}. {esc(s)}" for i, s in enumerate(subs, 1)) if subs else
            "(belum ada subgoal)\nTambah: <code>/subgoal teks…</code>")
        return
    if low == "clear":
        send_rich(chat_id, "✅ Subgoals dibersihkan."
                  if STATE.clear_subgoals(key) else "(belum ada goal)")
        return
    if low.startswith("remove ") or low.startswith("rm "):
        try:
            n = int(rest.split(None, 1)[1])
        except (ValueError, IndexError):
            send_rich(chat_id, "Pakai: <code>/subgoal remove N</code>")
            return
        send_rich(chat_id, "✅ Subgoal dihapus."
                  if STATE.remove_subgoal(key, n) else "❌ Nomer salah.")
        return
    if STATE.add_subgoal(key, rest):
        send_rich(chat_id, f"➕ <b>Subgoal</b> ditambah — judge ikut nilai.")
    else:
        send_rich(chat_id, "(belum ada goal — set dulu via "
                           "<code>/goal ...</code>)")


def handle_loop(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Prompt berulang di SESI ini (cron = terpisah ke home)."""
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    low = rest.lower()
    mine = {jid: j for jid, j in STATE.cron_list().items()
            if j.get("kind") == "loop" and str(j.get("chat_id")) == str(chat_id)}
    if not rest or low in ("status", "list"):
        if not mine:
            send_rich(chat_id, "(belum ada loop)\n"
                      "Contoh: <code>/loop 5m cek deploy</code> · "
                      "<code>/loop 1m cek antrian --times 10</code>")
            return
        lines = [f"{'✅' if j.get('enabled', True) else '⏸️'} "
                 f"<code>{jid}</code> [{esc(j.get('expr', ''))}] "
                 f"{esc((j.get('prompt') or '')[:50])}" for jid, j in mine.items()]
        send_rich(chat_id, "<b>Loops</b>\n" + "<br>".join(lines) +
                  "\n\n<code>/loop stop &lt;id&gt;</code>")
        return
    if low.startswith("stop ") or low.startswith("rm "):
        jid = rest.split(None, 1)[1]
        send_rich(chat_id, "✅ Loop dihentikan."
                  if STATE.cron_rm(jid) else "❌ ID nggak ketemu.")
        return
    parts = rest.split(None, 1)
    if len(parts) < 2:
        send_rich(chat_id, "Pakai: <code>/loop &lt;interval&gt; &lt;prompt&gt; "
                           "[--times N]</code>")
        return
    expr, prompt = parts
    times, m = -1, re.search(r"--times\s+(\d+)\s*$", prompt)
    if m:
        times = int(m.group(1))
        prompt = prompt[:m.start()].strip()
    iv = _parse_interval(expr)
    if iv is None or iv < 60:
        send_rich(chat_id, "Interval min <b>1m</b>, mis. "
                           "<code>/loop 5m cek deploy</code>.")
        return
    if not prompt:
        send_rich(chat_id, "Prompt-nya kosong.")
        return
    jid = STATE.cron_add({"kind": "loop", "expr": expr, "prompt": prompt,
                          "chat_id": chat_id, "thread_id": thread_id,
                          "enabled": True, "last_run": 0,
                          "created_by": user_id, "runs_left": times,
                          "runs_total": times if times > 0 else "∞"})
    send_rich(chat_id, f"🔁 <b>Loop {jid}</b> tiap {esc(expr)} aktif"
                       + (f" ({times}x)." if times > 0 else ".") +
                       "\nStop: <code>/loop stop " + jid + "</code>")


def handle_heartbeat(chat_id: int, thread_id, user_id: int,
                     args: list) -> None:
    """Prompt berkala yang masuk SESI ini hanya saat idle."""
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    low = rest.lower()
    if low.startswith("every "):
        rest = rest[len("every "):].strip()
    mine = {jid: j for jid, j in STATE.cron_list().items()
            if j.get("kind") == "heartbeat"
            and str(j.get("chat_id")) == str(chat_id)}
    if not rest or low in ("status", "list"):
        send_rich(chat_id, ("<b>Heartbeat</b>\n" + "<br>".join(
            f"{'✅' if j.get('enabled', True) else '⏸️'} <code>{jid}</code> "
            f"[{esc(j.get('expr', ''))}]" for jid, j in mine.items())
            + "\n\n<code>/heartbeat stop &lt;id&gt;</code>") if mine else
            "(belum ada heartbeat)\n"
            "Contoh: <code>/heartbeat every 5m ada update?</code>")
        return
    if low.startswith("stop ") or low.startswith("clear ") or \
            low.startswith("rm "):
        jid = rest.split(None, 1)[1]
        send_rich(chat_id, "✅ Heartbeat dihentikan."
                  if STATE.cron_rm(jid) else "❌ ID nggak ketemu.")
        return
    if low in ("pause", "resume"):
        send_rich(chat_id, "Pakai on/off per job: "
                           "<code>/cron off &lt;id&gt;</code>")
        return
    parts = rest.split(None, 1)
    if len(parts) < 2:
        send_rich(chat_id, "Pakai: <code>/heartbeat every 5m "
                           "&lt;prompt&gt;</code> (min 1m).")
        return
    expr, prompt = parts
    iv = _parse_interval(expr)
    if iv is None or iv < 60 or not prompt.strip():
        send_rich(chat_id, "Interval min <b>1m</b> + prompt tak kosong.")
        return
    jid = STATE.cron_add({"kind": "heartbeat", "expr": expr,
                          "prompt": prompt.strip(), "chat_id": chat_id,
                          "thread_id": thread_id, "enabled": True,
                          "last_run": 0, "created_by": user_id})
    STATE.note_activity(key)
    send_rich(chat_id, f"💓 <b>Heartbeat {jid}</b> tiap {esc(expr)} (idle "
                       "saja).\nStop: <code>/heartbeat stop " + jid + "</code>")


def handle_context(chat_id: int, thread_id, user_id: int,
                   args: list) -> None:
    """Gauge konteks sesi (teks, gaya Hermes messaging)."""
    from pipeline import _model_ctx_cached  # noqa: PLC0415 (hindari cycle)
    key = session_key(chat_id, thread_id)
    name, prof = resolve_profile(chat_id, thread_id)
    model = STATE.get_model(key) or prof.get("model") or ""
    ctx_len = _model_ctx_cached(model)
    u = STATE.get_usage(key)
    sid = STATE.get_session(key)
    extra_in = extra_out = 0
    if sid:
        try:
            info = executor.session_info(sid) or {}
            tok = info.get("tokens") or {}
            extra_in = int(tok.get("input") or 0)
            extra_out = int(tok.get("output") or 0)
        except Exception:  # noqa: BLE001
            pass
    total = u["input"] + u["output"] + extra_in + extra_out
    if ctx_len:
        pct = max(0, min(100, round(total / ctx_len * 100)))
        bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
    else:
        pct, bar = 0, "░" * 10
    send_rich(chat_id,
              "<b>Context</b>\n" + kv_block([
                  ("Model", (model or "?").split("/")[-1]),
                  ("Window", f"{ctx_len}" if ctx_len else "?"),
                  ("Terpakai", f"{bar} {pct}%"),
                  ("In/out", f"{fmt_tokens(total)} "
                             f"({fmt_tokens(u['input'] + extra_in)} / "
                             f"{fmt_tokens(u['output'] + extra_out)})"),
                  ("Saran", "/compress" if pct >= 70 else "aman"),
              ]))


def handle_queue(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Antre prompt giliran berikutnya tanpa interupsi (FIFO per chat)."""
    from pipeline import queue_depth  # noqa: PLC0415
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not rest or rest.lower() in ("list", "status"):
        send_rich(chat_id,
                  f"Antrean chat ini: <b>{queue_depth(key)}</b> job.\n"
                  "Tambah: <code>/queue prompt kamu</code>")
        return
    enqueue(key, lambda p=rest: run_agent(
        key, chat_id, thread_id, p))
    send_rich(chat_id, "📥 <b>Queued</b> — jalan setelah giliran ini "
                       f"(posisi {queue_depth(key)}).")


def handle_steer(chat_id: int, thread_id, user_id: int, args: list) -> None:
    key = session_key(chat_id, thread_id)
    rest = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not rest:
        send_rich(chat_id, "Pakai: <code>/steer fokus ke modul auth</code> — "
                           "catatan ditempel ke turn berikutnya.")
        return
    STATE.set_steer(key, f"{rest} (dari {user_id})")
    send_rich(chat_id, "🧭 <b>Steer noted</b> — ditempel ke turn berikut.")


def handle_branch(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Fork sesi di tempat: chat pindah ke cabang independen."""
    key = session_key(chat_id, thread_id)
    sid = STATE.get_session(key)
    if not sid:
        send_rich(chat_id, "Belum ada sesi — kirim pesan dulu.")
        return
    fk = executor.fork_session(sid)
    if not fk:
        send_rich(chat_id, "❌ Branch gagal (sesi kosong?).")
        return
    STATE.set_session(key, fk)
    name = " ".join(args[1:]).strip()
    if name:
        STATE.set_title(key, name)
    send_rich(chat_id, "🌿 <b>Branched</b> — chat ini sekarang di sesi "
                       f"<code>{esc(fk[:20])}</code> independen.")


def handle_plan(chat_id: int, thread_id, user_id: int, args: list) -> None:
    key = session_key(chat_id, thread_id)
    task = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if not task:
        send_rich(chat_id, "Pakai: <code>/plan migrasi auth ke JWT</code>")
        return
    prompt = ("Write an implementation plan (markdown) for this task and "
              "SAVE it under .hermes/plans/ in the workspace. Planning ONLY "
              f"— do NOT execute or modify code. Mention the saved path.\n\nTask: {task}")
    send_rich(chat_id, "🗺 <b>Planning…</b> (tanpa eksekusi)")
    enqueue(key, lambda p=prompt: run_agent(key, chat_id, thread_id, p))


def handle_egress(chat_id: int, thread_id, user_id: int, args: list) -> None:
    handle_command(chat_id, thread_id, user_id, ["/proxy"],
                   full_text="/proxy")


def handle_config(chat_id: int, thread_id, user_id: int, args: list) -> None:
    """Tampilkan config non-rahasia (token/ID disamarkan)."""
    tel = CFG.get("telegram", {})
    rows = [
        ("require_mention", tel.get("require_mention")),
        ("observe", tel.get("observe_unmentioned_group_messages")),
        ("footer", tel.get("footer")),
        ("notifications", tel.get("notifications")),
        ("inline_mode", tel.get("inline_mode")),
        ("batch_hold", (tel.get("batching") or {}).get("hold_sec")),
        ("max_turns(goal)", CFG.get("goals", {}).get("max_turns")),
        ("proxy", CFG.get("proxy", {}).get("enabled")),
        ("timeout", CFG["gateway"]["profiles"].get(
            CFG["gateway"]["routing"].get("default_profile",
                                          "default"), {}).get("timeout_sec")),
        ("allowed_users", f"{len(tel.get('allowed_users', []))} user"),
        ("group_chats", f"{len(tel.get('group_allowed_chats', []))} chat"),
    ]
    send_rich(chat_id, "<b>Config</b> (rahasia disembunyikan)\n" + kv_block([
        (k, v) for k, v in rows]))


def handle_command(chat_id: int, thread_id, user_id: int, args: list,
                   full_text: str = "", msg_id: int = 0) -> None:
    c = args[0].lower().lstrip("/").split("@")[0]
    key = session_key(chat_id, thread_id)

    if c in ("start", "help"):
        send_rich(chat_id, HELP_HTML)
    elif c == "keyboard":
        if len(args) >= 2 and args[1].lower() in ("off", "hide", "0"):
            hide_keyboard(chat_id)
        else:
            send_keyboard(chat_id)
    elif c == "status":
        name, prof = resolve_profile(chat_id, thread_id)
        model = STATE.get_model(key) or prof.get("model") or "profile default"
        agent = STATE.get_agent(key) or prof.get("agent") or "default"
        proxy = ("on (" + CFG["proxy"]["url"] + ")"
                 if CFG["proxy"].get("enabled") else "off")
        send_rich(chat_id,
                  "<b>Status</b>\n" + kv_block([
                      ("Profile", name),
                      ("Session", STATE.get_session(key) or "—"),
                      ("Model", model),
                      ("Agent", agent),
                      ("Workspace", prof.get("workspace")),
                      ("Timeout", f"{prof.get('timeout_sec')}s"),
                      ("Proxy", proxy),
                      ("Home", STATE.get_home() or "—"),
                      ("Sessions", len(STATE.list_sessions())),
                  ]),
                  {"inline_keyboard": [[
                      {"text": "Models", "callback_data": "nav:models"},
                      {"text": "Sessions",
                       "callback_data": "nav:sessions"}]]})
    elif c == "new":
        STATE.clear_session(key)
        TG.send(chat_id, "🧹 Sesi direset. Pesan berikutnya konteks baru.")
    elif c == "stop":
        sid = STATE.get_session(key)
        if not sid:
            send_rich(chat_id, "Nggak ada sesi yang lagi jalan.")
            return
        r = executor.interrupt(sid)
        if executor.is_err(r):
            send_rich(chat_id, f"❌ Gagal stop: {esc(r.get('__err', '')[:120])}")
        else:
            send_rich(chat_id, "🛑 Dihentikan.")
    elif c == "model":
        name, prof = resolve_profile(chat_id, thread_id)
        if len(args) < 2:
            # tampilkan pemilih model interaktif (tombol)
            text, kb = nav_content("models", chat_id, thread_id)
            send_rich(chat_id, text, kb)
        elif args[1].lower() == "reset":
            STATE.set_model(key, "")
            send_rich(chat_id, "✅ Balik ke model default profil.")
        else:
            STATE.set_model(key, args[1])
            send_rich(chat_id, f"✅ Model: <code>{esc(args[1])}</code>")
    elif c == "sethome":
        STATE.set_home(chat_id)
        send_rich(chat_id, f"📌 Home channel: <code>{esc(chat_id)}</code>")
    elif c == "proxy":
        if len(args) >= 3 and args[1].lower() == "auto" \
                and args[2].lower() in ("on", "off"):
            CFG["proxy"]["auto_rotate"] = args[2].lower() == "on"
            save_cfg(CFG)
            send_rich(chat_id, "Auto-rotate saat limit: <b>"
                      + ("ON" if CFG["proxy"]["auto_rotate"] else "OFF")
                      + "</b>")
        elif len(args) >= 2 and args[1].lower() in ("on", "off"):
            CFG["proxy"]["enabled"] = args[1].lower() == "on"
            save_cfg(CFG)
            msg = ("✅ Proxy <b>ON</b> <code>"
                   + esc(CFG["proxy"]["url"]) + "</code>") \
                if CFG["proxy"]["enabled"] else "✅ Proxy <b>OFF</b>"
            send_rich(chat_id, msg + "\nRestart server OpenCode…")
            try:
                ok = executor.restart_server(
                    bool(CFG["proxy"].get("enabled")))
                send_rich(chat_id, "✅ Server OpenCode restart: "
                          + ("OK" if ok else "GAGAL — cek log"))
            except Exception as e:  # noqa: BLE001
                send_rich(chat_id, f"❌ restart server gagal: {esc(e)[:120]}")
        else:
            on = bool(CFG["proxy"].get("enabled"))
            auto = bool(CFG["proxy"].get("auto_rotate", True))
            send_rich(chat_id, "⏳ Cek status proxy…")

            def _st():
                w = _warp_cli("status").split("\n")
                wsum = next((l for l in w
                             if "connected" in l.lower()
                             or "disconnected" in l.lower()
                             or "connecting" in l.lower()),
                            (w[0] if w else "?"))[:80]
                ip_p = _egress_ip(True)
                ip_d = _egress_ip(False)
                send_rich(chat_id,
                          "<b>Proxy WARP</b>\n" + kv_block([
                              ("Switch", "ON" if on else "OFF"),
                              ("Auto-rotate", "ON" if auto else "OFF"),
                              ("warp-cli", wsum),
                              ("Egress (proxy)", ip_p),
                              ("Egress (langsung)", ip_d),
                          ]) + "\n<code>/proxy on|off</code> · "
                          "<code>/proxy auto on|off</code> · "
                          "<code>/rotate</code> ganti IP · "
                          "<code>/limits</code> status limit")
            threading.Thread(target=_st, daemon=True).start()
    elif c == "rotate":
        send_rich(chat_id, "🔄 Rotate IP WARP…")

        def _rotate():
            old, new = rotate_egress()
            if new in ("?", "", old):
                send_rich(chat_id,
                          "❌ <b>Rotate gagal / IP sama</b>\n"
                          "Coba lagi nanti atau cek `warp-cli status` di VPS.")
            else:
                send_rich(chat_id,
                          "✅ <b>IP baru</b>\n" + kv_block([
                              ("Lama", old),
                              ("Baru", new),
                          ]) + "\nLimit provider nempel di IP — IP baru "
                          "sering lolos limit.")
            log(f"rotate {old} -> {new}")
        threading.Thread(target=_rotate, daemon=True).start()
    elif c == "limits":
        quota = STATE.get_quota()
        name, prof = resolve_profile(chat_id, thread_id)
        cur = STATE.get_model(session_key(chat_id, thread_id)) or \
            prof.get("model") or "(default)"
        if quota:
            rows = []
            for m, q in sorted(quota.items(), key=lambda kv: -kv[1]["hits"]):
                ts = time.strftime("%d %H:%M",
                                    time.localtime(q["last"])) \
                    if q["last"] else "-"
                rows.append((m.split("/")[-1][:22],
                             f"{q['hits']}x · {ts}"))
            body = kv_block(rows[:10])
        else:
            body = "(belum ada limit tercatat — bagus!)"
        send_rich(chat_id,
                  "<b>Rate limits</b>\n"
                  f"Model aktif: <code>{esc(cur)}</code>\n"
                  f"Egress: <code>{esc(_egress_ip(bool(CFG['proxy'].get('enabled'))))}</code>\n"
                  f"Auto-rotate: <b>{'ON' if CFG['proxy'].get('auto_rotate', True) else 'OFF'}</b> "
                  "(<code>/proxy auto on|off</code>)\n"
                  + body +
                  "\n\nKena limit? <code>/rotate</code> (ganti IP) · "
                  "<code>/model</code> (ganti model, kuota terpisah) · "
                  "tunggu beberapa menit.")
    elif c == "workspace":
        name, prof = resolve_profile(chat_id, thread_id)
        send_rich(chat_id,
                  f"📁 <code>{esc(os.path.expanduser(prof.get('workspace')))}</code>")
    elif c == "topic":
        send_rich(chat_id,
                  f"• chat: <code>{esc(chat_id)}</code>\n"
                  f"• thread: <code>{esc(thread_id or 'root')}</code>\n"
                  f"• sesi: <code>"
                  f"{esc(STATE.get_session(key) or '(belum ada)')}</code>")
    elif c == "platforms":
        bu = RUNTIME["bot_username"]
        send_rich(chat_id,
                  "🔌 <b>Platform</b>\n"
                  f"• telegram: ✅ @{esc(bu)}\n"
                  f"• polling: <b>{'OFF' if CFG['gateway']['webhook']['enabled'] else 'ON'}</b>\n"
                  f"• webhook: <b>{'ON' if CFG['gateway']['webhook']['enabled'] else 'OFF'}</b>")
    elif c == "restart":
        from pipeline import active_turns, wait_active  # noqa: PLC0415
        n = active_turns()
        TG.send(chat_id, "♻️ Restart gateway…"
                + (f"\nNunggu {n} turn selesai dulu…" if n else ""))
        STATE.set_restart_notice(chat_id, thread_id)
        log(f"restart diminta via /restart (turn aktif: {n})")
        time.sleep(1)
        if n and not wait_active(150):
            log("restart paksa: masih ada turn jalan")
        os._exit(3)
    elif c == "cron":
        handle_cron(chat_id, thread_id, user_id, args)
    elif c == "footer":
        if len(args) >= 2 and args[1].lower() in ("on", "off"):
            CFG["telegram"]["footer"] = args[1].lower() == "on"
            save_cfg(CFG)
        send_rich(chat_id, "Footer: <b>"
                  + ("ON" if CFG["telegram"].get("footer") else "OFF")
                  + "</b> — <code>/footer on|off</code>")
    elif c in ("goal", "goals"):
        handle_goal(chat_id, thread_id, user_id, args)
    elif c == "subgoal":
        handle_subgoal(chat_id, thread_id, user_id, args)
    elif c == "loop":
        handle_loop(chat_id, thread_id, user_id, args)
    elif c in ("heartbeat", "hb"):
        handle_heartbeat(chat_id, thread_id, user_id, args)
    elif c in ("context", "ctx"):
        handle_context(chat_id, thread_id, user_id, args)
    elif c in ("queue", "q"):
        handle_queue(chat_id, thread_id, user_id, args)
    elif c == "steer":
        handle_steer(chat_id, thread_id, user_id, args)
    elif c in ("branch", "fork"):
        handle_branch(chat_id, thread_id, user_id, args)
    elif c == "plan":
        handle_plan(chat_id, thread_id, user_id, args)
    elif c == "egress":
        handle_egress(chat_id, thread_id, user_id, args)
    elif c == "config":
        handle_config(chat_id, thread_id, user_id, args)
    else:
        if handle_extra(c, chat_id, thread_id, user_id, args, msg_id):
            return
        # gaya Hermes: /command tak dikenal = invokasi skill ke agent.
        # Timeout pendek (300s): skill asing tak boleh bakar turn panjang.
        skill_text = full_text or " ".join(args)
        send_rich(chat_id, f"Running <code>{esc(args[0])}</code> as a skill…")
        enqueue(key, lambda st=skill_text, a=args[0]: run_agent(
            key, chat_id, thread_id,
            f"{st}\n\n(The leading {a} is a skill name — use "
            "that skill if it exists, otherwise do the task directly. "
            "Be concise.)", timeout_override=300))


# ----------------------------------------------------------------------------
# dispatch
# ----------------------------------------------------------------------------
