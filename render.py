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


TOOL_PREVIEW_CAP = 40

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
        return one[:TOOL_PREVIEW_CAP - 3] + "..."
    return one


def progress_line(name: str, label: str, done: bool) -> str:
    """Satu baris progress ala Hermes: `💻 bash...` -> `💻 Running \"cmd\"`."""
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


def prog_html(tool_lines, limit: int = 3700) -> str:
    """Bubble progres ala Hermes: tool terminal jadi header + blok <pre>
    (header tak diulang untuk call terminal berurutan), sisanya baris
    single-line. Baris tertua dibuang bila melewati limit."""
    blocks: list = []
    for name, label, done in tool_lines.values():
        low = (name or "").lower()
        first_cmd = " ".join((label or "").splitlines()[0:1])[:200]
        if low in TERMINAL_TOOLS and _preview_40(first_cmd):
            cmd = esc(first_cmd)
            if blocks and blocks[-1][0] == f"t:{low}":
                blocks[-1][1].append(f"<pre>{cmd}</pre>")
            else:
                blocks.append((f"t:{low}",
                               [f"{tool_icon(name)} <b>{esc(name or 'tool')}</b>",
                                f"<pre>{cmd}</pre>"]))
        else:
            blocks.append((f"s:{name}:{label}:{done}",
                           [progress_line(name, label, done)]))
    lines = [ln for _, b in blocks for ln in b]
    text = "\n".join(lines)
    while len(blocks) > 1 and len(text) > limit:
        blocks.pop(0)
        lines = [ln for _, b in blocks for ln in b]
        text = "\n".join(lines)
    return text


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


def md_to_html(text: str) -> str:
    """Markdown umum -> HTML Telegram. Gagal -> plain (tak pernah throw)."""
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
                return _hold(f'<pre><code class="{_html.escape(lang)}">'
                              f"{code}</code></pre>")
            return _hold(f"<pre>{code}</pre>")

        # 0. inline ```code``` sebaris -> code biasa (bukan fence)
        text = re.sub(r"```([^`\n]+)```",
                      lambda m: _hold(f"<code>{_html.escape(m.group(1))}"
                                      "</code>"), text)
        # 1. fenced block: buka di awal baris & tutup di baris sendiri
        # (Hermes); inline ``` tak dimakan
        text = re.sub(r"(?m)^([^\n]*```[^\n]*\n)([\s\S]*?)(^[ \t]*```)[ \t]*$",
                      _fence, text)
        text = re.sub(r"`([^`\n]+)`",
                      lambda m: _hold(f"<code>{_html.escape(m.group(1))}"
                                      "</code>"), text)
        # 2. escape sisa HTML
        text = _html.escape(text)
        # 3. heading -> bold
        text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"<b>\1</b>", text)
        # 4. bold + italic + strike
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
        text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>",
                      text)
        text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>",
                      text)
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
        text = re.sub(r"\|\|(.+?)\|\|", r"<u>\1</u>", text)
        # 5. link [t](url) dukung parens dalam URL (Hermes) + bare url
        text = re.sub(r"\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
                      r'<a href="\2">\1</a>', text)
        text = re.sub(r"(?<![\"'=])(https?://[^\s<>]+)",
                      r'<a href="\1">\1</a>', text)
        # 6. blockquote per baris
        text = re.sub(r"(?m)^&gt;\s?(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        text = re.sub(r"(?m)^&gt;(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        text = re.sub(r"(?m)^>\s?(.*)$", r"<blockquote>\1</blockquote>",
                      text)
        # 7. kembalikan code
        for k, v in holders.items():
            text = text.replace(_html.escape(k), v).replace(k, v)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
    except Exception:  # noqa: BLE001
        return _html.escape(text or "")


def split_pages(html: str, limit: int = PAGE_SIZE) -> list:
    """Bagi HTML per halaman tanpa motong blok <pre>; bernomor bila >1."""
    if len(html) <= limit:
        return [html]
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
            balanced.append(p)
        pages = balanced
        n = len(pages)
        pages = [f"{p} ({k}/{n})" for k, p in enumerate(pages, 1)]
    return pages
