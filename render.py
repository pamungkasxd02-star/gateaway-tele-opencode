#!/usr/bin/env python3
"""Rendering ala Hermes: ikon/verb tool, silence, markdown->HTML Telegram,
tabel, pagination, footer runtime-metadata. Fungsi murni + baca CFG."""

import html as _html
import os
import re

from core import CFG, esc

TOOL_ICONS = {
    "shell": "💻", "bash": "💻", "terminal": "💻", "run": "💻",
    "execute": "💻", "execute_code": "🐍",
    "web_search": "🔍", "search": "🔍", "webfetch": "🔍",
    "fetch": "🌐", "web": "🌐", "browser": "🌐",
    "web_extract": "📄", "extract": "📄",
    "read": "📖", "view": "📖",
    "write": "✏️", "edit": "✏️", "patch": "✏️", "create": "✏️",
    "apply_patch": "✏️",
    "python": "🐍", "code": "🐍",
    "glob": "🗂", "ls": "🗂", "list": "🗂",
    "grep": "🔎", "codesearch": "🔎",
    "skill": "🧩", "skills": "🧩",
    "task": "🤖", "delegate": "🚀", "subagent": "🤖",
    "todowrite": "📋", "todoread": "📋", "todo": "📋",
    "question": "❓", "clarify": "❓", "ask": "❓",
    "plan": "🗺", "review": "🔎",
    "image": "🖼", "vision": "🖼",
    "memory": "🧠", "remember": "🧠",
    "think": "💭", "reasoning": "💭",
}


SILENCE_RE = re.compile(
    r"^[\s*_~`\[\]]*\(?\s*(silent|silence|no[\s_]+response|no[\s_]+reply)"
    r"\s*\.?\)?[\s*_~`\[\]]*$"
    r"|^[\s*_~`]*[🔇.…]+[\s*_~`]*$",
    re.IGNORECASE)


PREVIEW_TEXT = "💭 Thinking…"


TOOL_PREVIEW_CAP = 64

# Hermes: verb ramah per tool + connector (" for " khusus search-style).


TOOL_VERBS = {
    "bash": "Running", "shell": "Running", "terminal": "Running",
    "execute": "Running", "execute_code": "Running code",
    "read": "Reading", "view": "Reading",
    "write": "Writing", "create": "Writing",
    "edit": "Editing", "patch": "Editing",
    "grep": "Searching files", "codesearch": "Searching files",
    "webfetch": "Reading", "fetch": "Reading", "web_extract": "Reading",
    "web_search": "Searching the web", "search": "Searching the web",
    "task": "Delegating", "delegate": "Delegating",
    "subagent": "Delegating",
    "todo": "Updating tasks", "todowrite": "Updating tasks",
    "todoread": "Updating tasks",
}
TOOL_VERB_FOR = {"web_search", "search", "grep", "codesearch"}
TOOL_NO_PREVIEW = {"todo", "todowrite", "todoread"}


def _preview_40(label: str) -> str:
    one = " ".join((label or "").split())
    if len(one) > TOOL_PREVIEW_CAP:
        return one[:TOOL_PREVIEW_CAP - 1] + "…"
    return one


def progress_line(name: str, label: str, done: bool) -> str:
    """Satu baris progress ala Hermes: `💻 bash...` -> `💻 Running "cmd"`."""
    emoji = tool_icon(name)
    tool = (name or "tool").strip() or "tool"
    if not done:
        return f"{emoji} <b>{esc(tool)}</b>..."
    prev = _preview_40(label)
    verb = TOOL_VERBS.get(tool.lower())
    if tool.lower() in TOOL_NO_PREVIEW:
        return f"{emoji} {verb}" if verb else f"{emoji} <b>{esc(tool)}</b>..."
    if verb and prev:
        conn = " for " if tool.lower() in TOOL_VERB_FOR else " "
        return f'{emoji} {verb}{conn}"{esc(prev)}"'
    if prev and prev.lower() != tool.lower():
        return f'{emoji} {esc(tool)}: "{esc(prev)}"'
    return f"{emoji} <b>{esc(tool)}</b>..."


TERMINAL_TOOLS = {"bash", "shell", "terminal", "execute", "execute_code"}

# Bubble progres: tampilkan N tool terakhir, utuh per call.
PROG_MAX_TOOLS = 6
# Pengaman: bubble tak lebih dari N halaman (halaman pertama = terbaru?
# tidak — yang TERTUA dibuang dulu, jadi yang kelihatan selalu kerjaan
# terakhir). Satu halaman ~3700 char.
PROG_MAX_PAGES = 3


def _full_cmd(label: str) -> str:
    """Command UTUH buat <pre> (copyable + lengkap, tanpa potong).
    Hanya rapikan whitespace pinggir tiap baris."""
    lines = [(ln.rstrip()) for ln in (label or "").splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return " ".join((label or "").split())
    return "\n".join(lines)


def prog_html(tool_lines, limit: int = 3700, max_tools: int = PROG_MAX_TOOLS) -> str:
    """Bubble progres: tiap call bash = SATU blok <pre> UTUH.

    Aturan perfect ala operator: rapi (satu header `💻 bash ×N` per grup
    berurutan) + lengkap (isi tak dipotong sepatah kata pun) + bisa
    dicopy (selalu <pre>, bukan quote). Tool lain satu baris ringkas.
    Hanya N call terakhir; grup tertua dibuang bila lewat
    PROG_MAX_PAGES halaman.
    """
    items = list(tool_lines.values())
    if max_tools and len(items) > max_tools:
        items = items[-max_tools:]
    blocks: list = []
    for name, label, done in items:
        low = (name or "").lower()
        if low in TERMINAL_TOOLS:
            cmd = _full_cmd(label) or (name or "tool")
            if blocks and blocks[-1][0] == f"t:{low}":
                blocks[-1][1].append(f"<pre>{esc(cmd)}</pre>")
                n = len(blocks[-1][1]) - 1
                blocks[-1][1][0] = (
                    f"{tool_icon(name)} <b>{esc(name or 'tool')} ×{n}</b>")
            else:
                blocks.append((f"t:{low}",
                               [f"{tool_icon(name)} <b>{esc(name or 'tool')}</b>",
                                f"<pre>{esc(cmd)}</pre>"]))
        else:
            blocks.append((f"s:{name}:{label}:{done}",
                           [progress_line(name, label, done)]))
    def _join(bs):
        return "\n".join(ln for _, b in bs for ln in b)

    def _npages(bs):
        try:
            return len(split_pages(_join(bs), limit))
        except Exception:  # noqa: BLE001
            return 1

    def _retitle(b):
        key, lines = b
        if key.startswith("t:") and len(lines) > 1:
            n = len(lines) - 1
            base = re.sub(r" ×\d+</b>$", "</b>", lines[0])
            lines[0] = re.sub(r"</b>$", f" ×{n}</b>", base) if n > 1 else base

    while _npages(blocks) > PROG_MAX_PAGES:
        if not blocks:
            break
        b0 = blocks[0]
        if len(b0[1]) > 2:
            b0[1].pop(1)  # buang <pre> tertua, header + sisa utuh
            _retitle(b0)
        elif len(blocks) > 1:
            blocks.pop(0)  # blok kecil tua -> buang utuh
        else:
            break  # satu-satunya <pre> raksasa: biarkan UTUH, paging yg urus
    return _join(blocks)


def is_silence(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and len(stripped) <= 64 and bool(
        SILENCE_RE.match(stripped))


def tool_icon(name: str) -> str:
    return TOOL_ICONS.get((name or "").lower(), "🔧")


def fmt_latency(seconds: float) -> str:
    if seconds < 1:
        return "<1s"
    total = round(seconds)
    if total < 60:
        return f"{total}s"
    m, s = divmod(total, 60)
    return f"{m}m{s:02d}s"


def home_relative(path: str) -> str:
    if not path:
        return ""
    home = os.path.expanduser("~")
    p = os.path.abspath(path)
    if p == home or p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


def model_short(model: str) -> str:
    return model.rsplit("/", 1)[-1] if model else ""


def hermes_footer(model="", context_tokens=-1, context_length=0,
                  cwd="", latency=None) -> str:
    """Footer runtime-metadata gaya Hermes: model · N% · ~/cwd · 22s"""
    fields = CFG["telegram"].get("footer_fields",
                                 ["model", "context_pct", "cwd", "latency"])
    parts = []
    if "model" in fields and model:
        parts.append(model_short(model))
    if "context_pct" in fields and context_length and context_tokens >= 0:
        pct = max(0, min(100, round(context_tokens / context_length * 100)))
        parts.append(f"{pct}%")
    if "cwd" in fields and cwd:
        parts.append(home_relative(cwd))
    if "latency" in fields and latency is not None:
        parts.append(fmt_latency(latency))
    return " · ".join(parts)


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


PAGE_SIZE = 3800


TABLE_SEP_RE = re.compile(
    r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$")


def _split_row(line: str) -> list:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _render_table_block(block: list) -> str:
    """Satu tabel -> grup bold-heading + bullets (persis Hermes
    _render_table_block): heading = sel non-kosong pertama tiap baris."""
    headers = _split_row(block[0]) if len(block) >= 3 else []
    if len(headers) < 2:
        return "\n".join(block)
    has_label_col = len(_split_row(block[2])) == len(headers) + 1
    groups = []
    for idx, row in enumerate(block[2:], start=1):
        cells = _split_row(row)
        if has_label_col:
            heading = cells[0] if cells and cells[0] else f"Row {idx}"
            data = cells[1:]
        else:
            heading = next((c for c in cells if c), f"Row {idx}")
            data = cells
        data = (data + [""] * len(headers))[:len(headers)]
        bullets = [f"\u2022 {h}: {v}" for h, v in zip(headers, data)
                   if has_label_col or v != heading]
        groups.append("\n".join([f"**{heading}**", *bullets]))
    return "\n\n".join(groups)


def _normalize_tables(text: str) -> str:
    """Pipe-table GFM -> grup heading+bullets persis Hermes
    (convert_table_to_bullets). Fenced code dibiarkan; `---` tak cocok
    sebagai separator (butuh internal `|`)."""
    if "|" not in text or "-" not in text:
        return text
    lines = text.split("\n")
    out, i, in_fence = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if not in_fence and "|" in line and i + 1 < len(lines) \
                and TABLE_SEP_RE.match(lines[i + 1]):
            j = i + 2
            while j < len(lines) and "|" in lines[j].strip():
                j += 1
            out.append(_render_table_block(lines[i:j]))
            i = j
        else:
            out.append(line)
            i += 1
    return "\n".join(out)



_ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "blockquote",
                 "tg-spoiler"}
_TAG_RX = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^<>]*)?)>")


def _strip_to_plain(html_text: str) -> str:
    """Buang semua tag, unescape entity -> plain text aman Telegram."""
    no_tags = re.sub(r"<[^<>]+>", "", html_text)
    return _html.unescape(no_tags)


def _balance_or_plain(html_text: str) -> str:
    """Validasi tag HTML Telegram (nesting + atribut). Invalid -> plain.

    Ketat ala Hermes: hanya 8 tag, tak ada <br>/<p>/<div>,
    tak ada <pre> di dalam inline (b/i/a), semua harus seimbang.
    """
    try:
        stack = []
        for m in _TAG_RX.finditer(html_text):
            closing, name, attrs = m.group(1), m.group(2).lower(), (m.group(3) or "")
            if name not in _ALLOWED_TAGS:
                return _strip_to_plain(html_text)
            attrs = attrs.strip()
            if closing:
                if not stack or stack[-1] != name:
                    return _strip_to_plain(html_text)
                stack.pop()
                continue
            if name == "a":
                if not re.fullmatch(r'href="[^"<>]+"', attrs):
                    return _strip_to_plain(html_text)
                if "pre" in stack or "code" in stack:
                    return _strip_to_plain(html_text)
            elif name == "code":
                if attrs and not re.fullmatch(r'class="language-[a-zA-Z0-9+\-]{1,32}"', attrs):
                    return _strip_to_plain(html_text)
            elif attrs:
                return _strip_to_plain(html_text)
            if name == "pre" and any(s in ("b", "i", "u", "s", "a",
                                             "tg-spoiler") for s in stack):
                return _strip_to_plain(html_text)
            if name == "blockquote" and "pre" in stack:
                return _strip_to_plain(html_text)
            stack.append(name)
        if stack:
            return _strip_to_plain(html_text)
        # Tag tak dikenal yang lolos regex (mis. <br>, <p>): tolak.
        if re.search(r"</?(?:br|p|div|span|ul|ol|li|table|tr|td|h[1-6])[\s>/]", html_text, re.IGNORECASE):
            return _strip_to_plain(html_text)
        return html_text
    except Exception:
        return _strip_to_plain(html_text)


def md_to_html(text: str) -> str:
    """Markdown umum -> HTML Telegram. Gagal -> plain (tak pernah throw).

    Rapi ala Hermes: code difence diproteksi holder, inline bold/italic
    diproteksi per-match supaya tak bisa overlap lintas tag (penyebab
    'Unmatched end tag ... </i> vs </b>' yang bikin bubble hancur).
    """
    try:
        if not text:
            return ""
        text = _normalize_tables(text)
        holders: dict = {}

        def _hold(html: str) -> str:
            holders[f"\x00{len(holders)}\x00"] = html
            return f"\x00{len(holders) - 1}\x00"

        def _fence(m):
            lead, body = m.group(1), m.group(2)
            lang = lead.split("```", 1)[1].strip() if "```" in lead else ""
            code = _html.escape(body.strip("\n"))
            if lang:
                lang_safe = re.sub(r"[^a-zA-Z0-9+\-]", "", lang)[:32]
                if lang_safe:
                    return _hold(f'<pre><code class="language-{lang_safe}">'
                                  f"{code}</code></pre>")
            return _hold(f"<pre>{code}</pre>")

        # 0. inline ```code``` sebaris -> code biasa (bukan fence)
        text = re.sub(r"```([^`\n]+)```",
                      lambda m: _hold(f"<code>{_html.escape(m.group(1))}"
                                      "</code>"), text)
        # 1. fenced block: buka di awal baris & tutup di baris sendiri
        # (Hermes); inline ``` tak dimakan. Unclosed fence di ujung
        # dianggap tertutup (biar tak ada ``` mentah yang hancur).
        text = re.sub(r"(?m)^([^\n]*```[^\n]*\n)([\s\S]*?)(^[ \t]*```)[ \t]*$",
                      _fence, text)
        if text.count("```") % 2 == 1 or (
                re.search(r"(?m)^[^\n]*```[^\n]*$", text) and "```" in text):
            # satu fence gantung: bungkus sisa sampai akhir sebagai <pre>
            def _unclosed(m):
                lead, body = m.group(1), m.group(2)
                lang = lead.split("```", 1)[1].strip() if "```" in lead else ""
                code = _html.escape(body.strip("\n"))
                lang_safe = re.sub(r"[^a-zA-Z0-9+\-]", "", lang)[:32]
                if lang_safe:
                    return _hold(f'<pre><code class="language-{lang_safe}">'
                                  f"{code}</code></pre>")
                return _hold(f"<pre>{code}</pre>")
            text = re.sub(r"(?m)^([^\n]*```[^\n]*\n)([\s\S]*)$",
                          _unclosed, text, count=1)
        # 1b. blok indent (4 spasi/tab, >=2 baris berurutan) -> <pre>.
        # Output terminal yang lupa difence agent tetap tampil monospace
        # rapi, bukan teks jalan yang hancur. Konservatif: bukan list
        # markdown (`- `, `1. `), heading, quote, atau tabel — tapi output
        # `ls -l` (`-rw-r--r--`) dan IP (`127.0.0.1`) tetap lolos.
        _IND = r"(?:    |\t)"
        _NOT_MD = r"(?![-*+][ \t]|#{1,6}[ \t]|>|\d{1,3}[.)][ \t]|\|)"
        _IND_LINE = _IND + _NOT_MD + r"[^\n]*"
        def _indent_block(m):
            body = "\n".join(
                ln[4:] if ln.startswith("    ") else ln[1:]
                for ln in m.group(0).split("\n"))
            return _hold("<pre>" + _html.escape(body.strip("\n")) + "</pre>")
        text = re.sub(r"(?m)^" + _IND_LINE + r"(?:\n" + _IND_LINE + r")+",
                      _indent_block, text)
        text = re.sub(r"`([^`\n]+)`",
                      lambda m: _hold(f"<code>{_html.escape(m.group(1))}"
                                      "</code>"), text)
        # 2. escape sisa HTML
        text = _html.escape(text)
        # 3. heading -> bold + baris kosong (lega, tidak tindih dengan
        # paragraf bawahnya). Bold di DALAM judul dibuang dulu supaya
        # tak jadi <b> di dalam <b> yang rendernya tindih.
        def _heading(m):
            inner = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(1))
            inner = re.sub(r"__(.+?)__", r"\1", inner)
            return f"<b>{inner}</b>\n"
        text = re.sub(r"(?m)^#{1,6}\s+(.+)$", _heading, text)
        text = re.sub(r"(?m)^[ \t]*(?:---+|\*\*\*+|___+)[ \t]*$",
                      "────────\n", text)
        text = re.sub(r"(?m)^([ \t]*)[-*+][ \t]+", r"\1• ", text)
        text = re.sub(r"(?m)^([ \t]*)\d+[.)][ \t]+",
                      lambda m: f"{m.group(1)}{m.group(0).strip().split()[0]} ",
                      text)

        # 4. bold/italic/strike/spoiler — tiap hasil langsung di-holder
        # supaya pola berikutnya tak bisa match melintasi tag (overlap
        # = sumber 'can't parse entities' di Telegram).
        def _fmt(pat, tag_open, tag_close):
            def _sub(m):
                inner = m.group(1)
                # pola sudah melarang <> mentah; holder \x00 diizinkan
                # (nested valid, direstore belakangan).
                if "<" in inner or ">" in inner:
                    return m.group(0)
                return _hold(f"{tag_open}{inner}{tag_close}")
            return _sub

        # bold dulu (agar ** tak dimakan italic *), isi boleh holder
        # (\x00) tapi tak boleh tag <> — nested valid, overlap impossible
        # karena tag sudah jadi holder opaque.
        text = re.sub(r"\*\*([^<>]+?)\*\*",
                      _fmt(None, "<b>", "</b>"), text)
        text = re.sub(r"__([^<>]+?)__",
                      _fmt(None, "<b>", "</b>"), text)
        text = re.sub(r"(?<!\w)\*(?!\s)([^<>]+?)(?<!\s)\*(?!\w)",
                      _fmt(None, "<i>", "</i>"), text)
        text = re.sub(r"(?<!\w)_(?!\s)([^<>]+?)(?<!\s)_(?!\w)",
                      _fmt(None, "<i>", "</i>"), text)
        text = re.sub(r"~~([^<>]+?)~~",
                      _fmt(None, "<s>", "</s>"), text)
        text = re.sub(r"\|\|([^<>]+?)\|\|",
                      _fmt(None, "<tg-spoiler>", "</tg-spoiler>"), text)
        # 5. link [t](url) dukung parens dalam URL (Hermes) + bare url.
        # Judul link tak boleh mengandung holder code yang belum restore?
        # Boleh — holder \x00 aman di dalam <a>, direstore belakangan.
        def _link(m):
            title, url = m.group(1), m.group(2).strip()
            if "\n" in url or " " in url and not url.startswith("http"):
                pass
            url = url.strip("<>")
            if not re.match(r"https?://|mailto:|tg://", url):
                return m.group(0)
            if "<" in title and "\x00" not in title:
                return m.group(0)
            return _hold(f'<a href="{_html.escape(url, quote=True)}">{title}</a>')
        text = re.sub(r"\[([^\]\n]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
                      _link, text)
        text = re.sub(r"(?<![\"'=\x00])(https?://[^\s<>\x00]+)",
                      lambda m: _hold(f'<a href="{m.group(1)}">{m.group(1)}</a>'),
                      text)
        # 6. blockquote per baris (setelah link; isi sudah holder-aman),
        # lalu gabung baris quote berurutan jadi SATU kotak (satu garis
        # abu, bukan rentetan kotak).
        text = re.sub(r"(?m)^&gt;\s?(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        text = re.sub(r"(?m)^&gt;(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        text = re.sub(r"(?m)^>\s?(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        text = re.sub(r"</blockquote>\n<blockquote>", "\n", text)
        # 7. kembalikan semua holder (code + inline fmt + link).
        # Urutan BALIK (luar dulu, dalam belakangan) supaya holder
        # bersarang (mis. <tg-spoiler>spoiler <b>bold</b></tg-spoiler>)
        for k, v in reversed(list(holders.items())):
            text = text.replace(_html.escape(k), v).replace(k, v)
        # Sisa holder (seharusnya tak ada) → buang biar tak ada \x00 mentah.
        if "\x00" in text:
            text = re.sub(r"\x00\d+\x00", "", text)
        # Lega: baris kosong di sekitar blok <pre> (kotak tak nempel/
        # tindih dengan paragraf), lalu rapikan newline berlebih.
        text = re.sub(r"([^\n])\n(<pre>)", r"\1\n\n\2", text)
        text = re.sub(r"(</pre>)\n([^\n])", r"\1\n\n\2", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return _balance_or_plain(text)
    except Exception:  # noqa: BLE001
        return _html.escape(text or "")


def split_pages(html: str, limit: int = PAGE_SIZE, number: bool = True) -> list:
    """Bagi HTML per halaman tanpa motong blok <pre>; bernomor bila >1
    (number=False untuk bubble progres yang diedit in-place).

    Tiap halaman divalidasi via _balance_or_plain — halaman yang
    terpotong di tengah tag (b/i/a/blockquote) jatuh ke plain aman,
    bukan error 'can't parse entities' yang hancur di Telegram.
    """
    def _valid(p: str) -> str:
        v = _balance_or_plain(p)
        # _balance_or_plain mengembalikan plain (tanpa tag) bila invalid;
        # bedakan dengan cara cek: bila ada tag tersisa yang invalid,
        # plain sudah aman dikirim.
        return v
    if len(html) <= limit:
        return [_valid(html)]
    paras = re.split(r"\n\s*\n", html)
    pages, cur = [], ""
    for p in paras:
        add = (p if not cur else "\n\n" + p)
        if len(cur) + len(add) <= limit:
            cur += add
        else:
            if cur:
                pages.append(cur)
            if len(p) > limit:  # paragraf raksasa: potong per baris
                buf = ""
                for ln in p.split("\n"):
                    while len(ln) > limit:  # baris tunggal overlong: cacah
                        if buf.strip():
                            pages.append(buf)
                            buf = ""
                        pages.append(ln[:limit])
                        ln = ln[limit:]
                    if len(buf) + len(ln) + 1 > limit:
                        if buf.strip():
                            pages.append(buf)
                        buf = ln
                    else:
                        buf = ln if not buf else buf + "\n" + ln
                cur = buf
            else:
                cur = p
    if cur:
        pages.append(cur)
    if len(pages) > 1:
        # seimbangkan <pre> lintas halaman ala Hermes (tutup di akhir
        # chunk, buka lagi di lanjutannya) biar HTML tetap valid
        balanced, carry = [], False
        for p in pages:
            if carry:
                p = "<pre>" + p
            d = p.count("<pre>") - p.count("</pre>")
            if d > 0:
                p += "</pre>"
                carry = True
            else:
                carry = False
            balanced.append(_valid(p))
        pages = balanced
        if number:
            n = len(pages)
            pages = [f"{p} ({k}/{n})" for k, p in enumerate(pages, 1)]
        return pages
    return [_valid(p) for p in pages]
