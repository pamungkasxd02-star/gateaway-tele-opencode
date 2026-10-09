#!/usr/bin/env python3
"""OpenCode <-> Telegram Gateway (Hermes-style) — entry point.

Modul besar sudah dipecah rapi:
  core.py      config/state/log/helper
  tg.py        transport Telegram + pesan kaya
  render.py    rendering jawaban ala Hermes
  pipeline.py  antrean/run_agent/cron/STT
  commands.py  semua command + tombol
  dispatch.py  routing update Telegram
  executor.py  client HTTP API OpenCode (tak berubah)
Jalankan: python3 gateway.py  (atau via service oc-telegram)
"""

import json
import os
import sys
import threading
import time
import urllib.parse

import executor
from core import CACHE_DIR, CFG, RUNTIME, STATE, log
from dispatch import handle_update
from pipeline import cron_loop
from tg import TG

def run_webhook() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    wh = CFG["gateway"]["webhook"]
    secret = wh.get("secret", "")
    port = int(wh.get("port", 8443))
    if not secret:
        log("FATAL: webhook.secret wajib kalau webhook diaktifkan")
        sys.exit(1)
    r = TG.call("setWebhook",
                url=wh.get("url", ""), secret_token=secret,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=CFG["telegram"].get(
                    "drop_pending_on_cold_boot", True))
    log(f"setWebhook -> {str(r)[:120]}")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.headers.get(
                    "X-Telegram-Bot-Api-Secret-Token") != secret:
                self.send_response(403)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            self.send_response(200)
            self.end_headers()
            try:
                threading.Thread(target=handle_update,
                                 args=(json.loads(body),),
                                 daemon=True).start()
            except Exception as e:  # noqa: BLE001
                log(f"webhook parse error: {e}")

    log(f"webhook listen 127.0.0.1:{port}{urllib.parse.urlparse(wh.get('url','')).path}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


_admit = threading.BoundedSemaphore(value=32)


def _handle_async(u: dict) -> None:
    """Dispatch update di worker thread: polling tak pernah macet gara-gara
    download media / transkrip yang lambat (satu pesan berat tak boleh
    membekukan seluruh bot)."""
    with _admit:
        try:
            handle_update(u)
        except Exception as e:  # noqa: BLE001
            log(f"handle_update error: {e}")


def run_polling() -> None:
    offset = TG.drop_pending() \
        if CFG["telegram"].get("drop_pending_on_cold_boot", True) else 0
    log(f"polling start offset={offset}")
    while True:
        try:
            from pipeline import _shutdown  # noqa: PLC0415
            if _shutdown.is_set():
                log("polling stop (shutdown)")
                return
            r = TG.get_updates(offset, CFG["poll_timeout"])
            if r and r.get("ok"):
                for u in r["result"]:
                    offset = u["update_id"] + 1
                    threading.Thread(target=_handle_async, args=(u,),
                                     daemon=True).start()
        except KeyboardInterrupt:
            log("stop")
            return
        except Exception as e:  # noqa: BLE001
            log(f"loop error: {e}")
            time.sleep(5)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------


def _mark_offline(*a) -> None:
    try:
        if CFG["telegram"].get("status_indicator"):
            TG.set_short_description("🔴 Offline")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pipeline import _shutdown, active_turns, wait_active  # noqa: PLC0415
        _shutdown.set()
        n = active_turns()
        log(f"gateway stop (turn aktif: {n})")
        if n:
            wait_active(150)
    except Exception:  # noqa: BLE001
        pass
    log("gateway stop")
    os._exit(0)


def main() -> None:
    import signal as _signal
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            _signal.signal(sig, _mark_offline)
        except Exception:  # noqa: BLE001
            pass
    os.makedirs(CACHE_DIR, exist_ok=True)
    me = TG.get_me()
    if not me:
        log("FATAL: nggak bisa kontak Telegram (token salah / jaringan?).")
        sys.exit(1)
    me_id = me.get("id", 0)
    me_user = me.get("username", "")
    RUNTIME["bot_id"] = me_id
    RUNTIME["bot_username"] = me_user
    log(f"gateway start — bot @{me_user} (id={me_id})")
    TG.set_commands(CFG["telegram"].get("command_menu", []))
    if CFG["telegram"].get("status_indicator"):
        TG.set_short_description("🟢 Online")
    proxy_on = bool(CFG["proxy"].get("enabled"))
    if executor.ensure_server(proxy_on):
        log(f"server privat OpenCode siap di {executor.BASE} "
            f"(proxy={'ON' if proxy_on else 'OFF'})")
    else:
        log("PERINGATAN: server privat OpenCode gagal dihidupkan")
    log(f"allowed_users={CFG['telegram']['allowed_users']} "
        f"proxy_agent={'ON' if CFG['proxy'].get('enabled') else 'OFF'} "
        f"webhook={CFG['gateway']['webhook']['enabled']} "
        f"cron={len(STATE.cron_list())} job")
    _stop = threading.Event()
    threading.Thread(target=cron_loop, args=(_stop,), daemon=True).start()
    _notice = STATE.pop_restart_notice()
    if _notice:
        try:
            TG.send(_notice.get("chat_id"),
                    "✅ Gateway restarted — sesi lanjut.")
        except Exception:  # noqa: BLE001
            pass
    if CFG["gateway"]["webhook"]["enabled"]:
        run_webhook()
    else:
        run_polling()


if __name__ == "__main__":
    main()
