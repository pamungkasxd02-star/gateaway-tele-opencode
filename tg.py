#!/usr/bin/env python3
"""Transport Telegram (stdlib; curl hanya untuk upload file)."""

import hashlib
import html as _html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from core import CACHE_DIR, CFG, esc, log

TOKEN = CFG["telegram"]["bot_token"]


SEND_MAX_BYTES = 48 * 1024 * 1024  # limit Bot API 50MB, kasih headroom


class Telegram:
    def __init__(self) -> None:
        base = (CFG["telegram"].get("base_url") or "").rstrip("/")
        base_file = (CFG["telegram"].get("base_file_url") or "").rstrip("/")
        token = TOKEN
        # local Bot API server (file >20MB -> 2GB); sama kayak Hermes
        self.api = f"{base}/{token}" if base else \
            f"https://api.telegram.org/bot{token}"
        self.file_api = f"{base_file}/{token}" if base_file else \
            f"https://api.telegram.org/file/bot{token}"
        self.local_mode = bool(base)
        self.proxy = CFG["telegram"].get("proxy_url", "")

    def _opener(self):
        if not self.proxy:
            return urllib.request.build_opener()
        return urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": self.proxy, "https": self.proxy}))

    def call(self, method: str, http_timeout: int = 60, _retried=False,
             **params):
        data = json.dumps(params).encode()
        req = urllib.request.Request(
            f"{self.api}/{method}", data=data,
            headers={"Content-Type": "application/json"})
        try:
            with self._opener().open(req, timeout=http_timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode(errors="replace") or "{}")
            except Exception:  # noqa: BLE001
                body = {}
            # flood control ala Hermes: tunggu retry_after lalu coba sekali lagi
            if e.code == 429 and not _retried:
                wait = 0
                try:
                    wait = int((body.get("parameters") or {})
                               .get("retry_after", 0))
                except (TypeError, ValueError):
                    wait = 0
                wait = max(1, min(wait or 3, 60))
                log(f"TG {method} 429: tunggu {wait}s lalu retry")
                time.sleep(wait)
                return self.call(method, http_timeout=http_timeout,
                                 _retried=True, **params)
            if e.code != 429:
                desc = str(body.get("description", ""))
                # "not modified" = no-op rutin (edit dgn konten identik),
                # bukan error — jangan penuhi log
                if "not modified" not in desc:
                    log(f"TG {method} HTTP {e.code}: {desc[:160]}")
            return body or {"ok": False, "error_code": e.code}
        except Exception as e:  # noqa: BLE001
            log(f"TG {method} error: {e}")
        return None

    def get(self, method: str, http_timeout: int = 60):
        try:
            with self._opener().open(f"{self.api}/{method}",
                                     timeout=http_timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            log(f"TG GET {method} error: {e}")
            return None

    # -- high level ----------------------------------------------------------

    @staticmethod
    def _is_parse_error(r) -> bool:
        desc = str((r or {}).get("description", "")).lower()
        return "can't parse entities" in desc or "can't parse" in desc

    def send(self, chat_id, text: str, silent: bool = False,
             reply_to: int = 0) -> int:
        text = text or "(kosong)"
        mid = 0
        for i in range(0, len(text), 4000):
            params = dict(chat_id=chat_id, text=text[i:i + 4000],
                          disable_web_page_preview=True)
            if silent:
                params["disable_notification"] = True
            if reply_to and i == 0:
                params["reply_parameters"] = {"message_id": reply_to}
            r = self.call("sendMessage", **params)
            mid = ((r or {}).get("result") or {}).get("message_id", 0) or mid
        return mid

    def send_html(self, chat_id, html: str, silent: bool = False,
                  reply_to: int = 0) -> int:
        """Kirim HTML; fallback ke plain text kalau parse gagal."""
        r = self.call("sendMessage", chat_id=chat_id, text=html[:4000],
                      parse_mode="HTML", disable_web_page_preview=True,
                      **({"disable_notification": True} if silent else {}),
                      **({"reply_parameters": {"message_id": reply_to}}
                         if reply_to else {}))
        if r and r.get("ok"):
            return (r.get("result") or {}).get("message_id", 0)
        if self._is_parse_error(r):
            plain = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote|a)(?:\s[^<>]*)?>",
                           "", html or "")
            plain = _html.unescape(plain)
            return self.send(chat_id, plain, silent=silent,
                             reply_to=reply_to)
        return 0

    def edit(self, chat_id, message_id, text: str) -> None:
        r = self.call("editMessageText", chat_id=chat_id,
                      message_id=message_id, text=text[:4000],
                      disable_web_page_preview=True)
        if r is not None and not r.get("ok"):
            desc = str(r.get("description", ""))
            if "not modified" not in desc \
                    and "message to edit" not in desc \
                    and "message can't be edited" not in desc:
                log(f"TG edit gagal: {desc[:120]}")

    def edit_html(self, chat_id, message_id, html: str) -> bool:
        """Edit pakai HTML; fallback plain. True kalau pesannya berubah."""
        r = self.call("editMessageText", chat_id=chat_id,
                      message_id=message_id, text=html[:4000],
                      parse_mode="HTML", disable_web_page_preview=True)
        if r and r.get("ok"):
            return True
        if self._is_parse_error(r):
            plain = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote|a)(?:\s[^<>]*)?>",
                           "", html or "")
            self.edit(chat_id, message_id, _html.unescape(plain))
            return True
        return False

    def pin(self, chat_id, message_id) -> None:
        try:
            self.call("pinChatMessage", chat_id=chat_id,
                      message_id=message_id, disable_notification=True)
        except Exception:  # noqa: BLE001
            pass

    def unpin(self, chat_id, message_id) -> None:
        try:
            self.call("unpinChatMessage", chat_id=chat_id,
                      message_id=message_id)
        except Exception:  # noqa: BLE001
            pass

    def typing(self, chat_id) -> None:
        self.call("sendChatAction", chat_id=chat_id, action="typing")

    def set_short_description(self, text: str) -> None:
        self.call("setMyShortDescription", short_description=text)

    def set_commands(self, menu) -> None:
        self.call("setMyCommands", commands=menu)

    def get_me(self):
        r = self.get("getMe")
        return (r or {}).get("result") or {}

    def get_updates(self, offset: int, long_poll: int):
        """offset & timeout(Telegram long-poll) dikirim sebagai params."""
        allowed = ["message", "callback_query"]
        if CFG["telegram"].get("inline_mode"):
            allowed.append("inline_query")
        params = {"offset": offset, "timeout": long_poll,
                  "allowed_updates": allowed}
        return self.call("getUpdates", http_timeout=long_poll + 15, **params)

    def drop_pending(self) -> int:
        """Buang backlog di cold start. Kembalikan offset awal."""
        r = self.call("getUpdates", http_timeout=15, offset=-1, limit=1)
        res = (r or {}).get("result") or []
        return (res[-1]["update_id"] + 1) if res else 0

    def download(self, file_id: str, subdir: str, ext_hint: str = ""):
        r = self.call("getFile", file_id=file_id)
        if not (r and r.get("ok")):
            return None
        fp = (r.get("result") or {}).get("file_path", "")
        if not fp:
            return None
        ext = os.path.splitext(fp)[1] or ext_hint or ""
        os.makedirs(os.path.join(CACHE_DIR, subdir), exist_ok=True)
        name = f"{subdir}_{hashlib.md5(fp.encode()).hexdigest()[:12]}{ext}"
        path = os.path.join(CACHE_DIR, subdir, name)
        if not os.path.exists(path):
            try:
                with self._opener().open(f"{self.file_api}/{fp}",
                                         timeout=120) as resp, \
                        open(path, "wb") as f:
                    f.write(resp.read())
            except Exception as e:  # noqa: BLE001
                log(f"download {file_id} gagal: {e}")
                return None
        return path

    def send_media(self, chat_id, path: str, kind: str) -> bool:
        if not os.path.isfile(path):
            log(f"MEDIA tidak ada: {path}")
            self.send(chat_id, f"⚠️ File nggak ketemu: {path}")
            return False
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        if size > SEND_MAX_BYTES:
            mb = size / (1024 * 1024)
            log(f"MEDIA kebesaran ({mb:.0f}MB): {path}")
            self.send(chat_id,
                      f"⚠️ File kebesaran ({mb:.0f}MB, maks 48MB): "
                      f"{os.path.basename(path)}")
            return False
        method = {"document": "sendDocument", "photo": "sendPhoto",
                  "audio": "sendAudio", "video": "sendVideo"}[kind]
        cmd = ["curl", "-sS", "-m", "120", "-F", f"chat_id={chat_id}",
               "-F", f"{kind}=@{path}", f"{self.api}/{method}"]
        if kind == "video":
            cmd[5:5] = ["-F", "supports_streaming=true"]
        if self.proxy:
            cmd[3:3] = ["-x", self.proxy]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=130).stdout
            if not json.loads(out).get("ok"):
                log(f"send_media gagal: {out[:200]}")
                return False
            return True
        except Exception as e:  # noqa: BLE001
            log(f"send_media error: {e}")
            return False


TG = Telegram()


def send_rich(chat_id, text: str, keyboard=None) -> None:
    """Pesan ber-HTML (buatan gateway) + optional inline keyboard.

    Tiap potongan lewat send_html: kalau pecah di tengah tag dan parse
    gagal, otomatis fallback plain — tidak ada potongan yang hilang.
    """
    text = text or "(kosong)"
    first = True
    for i in range(0, len(text), 4000):
        chunk = text[i:i + 4000]
        kb = keyboard if first else None
        first = False
        if kb:
            r = TG.call("sendMessage", chat_id=chat_id, text=chunk,
                        parse_mode="HTML", disable_web_page_preview=True,
                        reply_markup=json.dumps(kb))
            if r and r.get("ok"):
                continue
            if r and not TG._is_parse_error(r):
                continue
            plain = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote|a)"
                           r"(?:\s[^<>]*)?>", "", chunk)
            TG.call("sendMessage", chat_id=chat_id,
                    text=_html.unescape(plain),
                    disable_web_page_preview=True,
                    reply_markup=json.dumps(kb))
        else:
            TG.send_html(chat_id, chunk)


def edit_rich(chat_id, message_id, text: str, keyboard=None) -> None:
    if keyboard is not None:
        r = TG.call("editMessageText", chat_id=chat_id,
                    message_id=message_id, text=text[:4000],
                    parse_mode="HTML", disable_web_page_preview=True,
                    reply_markup=json.dumps(keyboard))
        if r and (r.get("ok") or not TG._is_parse_error(r)):
            return
        plain = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote|a)"
                       r"(?:\s[^<>]*)?>", "", text or "")
        TG.call("editMessageText", chat_id=chat_id, message_id=message_id,
                text=_html.unescape(plain)[:4000],
                disable_web_page_preview=True,
                reply_markup=json.dumps(keyboard))
        return
    TG.edit_html(chat_id, message_id, text or "")


def kv_block(rows) -> str:
    """Blok key-value rata (dalam <pre>) — gaya bersih Hermes."""
    width = max(len(str(k)) for k, _ in rows)
    lines = [f"{str(k).ljust(width)}  {v}" for k, v in rows]
    return "<pre>" + esc("\n".join(lines)) + "</pre>"
