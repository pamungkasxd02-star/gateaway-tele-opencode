# OpenCode <-> Telegram Gateway (Hermes-style)

Jembatan mirip **Hermes gateway**: chat dari Telegram (DM / group / forum topic)
dijalankan sebagai prompt **OpenCode** di VPS ini, hasilnya dibalas ke Telegram.

```
Telegram ──polling──► gateway.py ──► opencode run --standalone ──► reply ke Telegram
```

## Fitur (Hermes-parity)

| Fitur | Status |
|---|---|
| Long polling / webhook mode | ✅ |
| Sesi terisolasi per chat & per topic | ✅ |
| Group chat + require_mention / mention_patterns | ✅ |
| Voice, audio, foto, dokumen → diteruskan ke agent | ✅ |
| Kirim file balik via tag `MEDIA:/path` | ✅ |
| Footer metadata (model, sesi, durasi) | ✅ |
| Command menu (`setMyCommands`) + indikator Online/Offline | ✅ |
| Multi-profile routing (chat/thread → workspace/model) | ✅ |
| Concurrency pool, dedup update, timeout + kill | ✅ |
| `/proxy on|off` + `/rotate` (ganti IP WARP) | ✅ |
| Cron / scheduled tasks | ✅ `/cron add/list/rm/on/off` → hasil ke home channel |
| Approval `/approve` `/deny` | ✅ regex berbahaya + permission API OpenCode |

## Setup (harus lu lakukan sendiri — 3 langkah)

### 1. Bikin bot
Chat [@BotFather](https://t.me/BotFather) → `/newbot` → ikuti instruksi → simpan **token**.

Opsional tapi disarankan:
- `/setdescription` dan `/setabouttext`
- `/setcommands` (boleh dilewati, gateway yang daftarkan otomatis)
- Kalau mau dipakai di **group**: Bot Settings → *Group Privacy* → **Turn off**
  (lalu **keluar & masuk ulang** bot ke grupnya)

### 2. Cari User ID Telegram
Chat [@userinfobot](https://t.me/userinfobot) → dia balas angka user ID lu.

### 3. Isi `.env` (token & ID, ala Hermes: rahasia di `.env`, config polos)
```bash
cp /home/ubuntu/oc-gateway/.env.example /home/ubuntu/oc-gateway/.env
nano /home/ubuntu/oc-gateway/.env
chmod 600 /home/ubuntu/oc-gateway/.env
```
Isi minimal:
```bash
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_ALLOWED_USERS=123456789
```
Opsional: `TELEGRAM_HOME_CHANNEL`, `TELEGRAM_GROUP_ALLOWED_CHATS`,
`TELEGRAM_GROUP_ALLOWED_USERS` (grup saja, tanpa DM),
`TELEGRAM_CRON_THREAD_ID`, `GROQ_API_KEY` / `OPENAI_API_KEY` (STT),
`HERMES_TELEGRAM_NOTIFICATIONS=all`. Service systemd memuat `.env`
otomatis via `EnvironmentFile`; jalan manual (`python3 gateway.py`) ikut
kebaca lewat loader built-in. `config.json` tidak lagi menyimpan rahasia
(token di sana cukup `${TELEGRAM_BOT_TOKEN}`).

## Menjalankan

```bash
# hidupkan service
sudo systemctl daemon-reload
sudo systemctl enable --now oc-telegram
sudo systemctl status oc-telegram

# log
tail -f /home/ubuntu/oc-gateway/gateway.log
```

Test: kirim pesan ke bot di Telegram → balasan datang dalam beberapa detik.

**Tombol cepat permanen**: kirim `/start` (atau `/keyboard`) → keyboard
`🆕 New · 📊 Status · 🧠 Model · ⏰ Cron · 🌐 Proxy · ❓ Help` muncul di
atas kolom chat dan nempel terus. Tap = langsung jalan, tanpa ketik slash.
Bedanya dengan `/menu`: `/menu` itu tombol inline di dalam bubble (hilang
kalau chat jalan), keyboard ini permanen.

## Command Telegram (Hermes-parity)

| Command | Fungsi |
|---|---|
| `/help` | daftar semua command |
| `/new` · `/reset` | percakapan baru |
| `/retry` | jalankan ulang pesan terakhir |
| `/undo` | hapus pertukaran terakhir |
| `/compress` | padatkan konteks percakapan |
| `/title [name]` | set judul sesi |
| `/resume [name]` | lanjutkan sesi bernama |
| `/sessions [search <q>]` | daftar/cari sesi (+ tombol pilih) |
| `/stop` | batalkan proses yang jalan |
| `/bg <prompt>` | jalankan di background, hasilnya dikirim lagi ke chat |
| `/btw <question>` | pertanyaan sampingan (sesi terpisah) |
| `/model [provider:model]` | lihat/ganti model |
| `/models` · `/agents` · `/agent [name]` | daftar + tombol pilih |
| `/personality [name]` | persona (dari config `personalities`) |
| `/reasoning on\|off` | tampilkan/sembunyikan reasoning |
| `/status` | info sesi (kv block) |
| `/usage` | token usage sesi ini |
| `/insights` | statistik opencode |
| `/whoami` | user/chat/akses |
| `/mcp` · `/auth` · `/plugins` · `/update` | mirror CLI opencode |
| `/approve` · `/deny` | approval buat prompt berbahaya (gateway deteksi `rm -rf`, `mkfs`, dll) |
| `/sethome` · `/platforms` · `/platform list` | manajemen gateway |
| `/proxy on\|off` · `/rotate` · `/limits` | WARP (IP keluar agent) + status limit |
| `/cron list` · `/cron add <expr> <prompt>` · `/cron rm/on/off <id>` | scheduled task ala Hermes |
| `/goal teks` · `/goal status|pause|resume|clear` · `/subgoal` | standing goal Ralph-loop |
| `/loop 5m ... [--times N]` · `/heartbeat every 5m ...` | prompt berulang sesi/idle |
| `/queue` · `/steer` · `/branch` · `/plan` · `/context` · `/config` · `/egress` | antre/arah/cabang/rencana/konteks |
| `/menu` | menu tombol interaktif |
| `/keyboard` | tampilkan tombol cepat permanen |
| `/restart` | restart gateway |
| `/<skill-name>` | command tak dikenal → diteruskan ke agent sebagai skill |

Expr cron: `10s|5m|2h|1d`, `every 30m`, `daily 07:00`, atau cron
`m h dom mon dow` (mis. `*/15 * * * *`). Hasil dikirim ke home channel
(`/sethome` dulu). Contoh: `/cron add 30m cek harga BTC lalu ringkas`.

**Proxy & limit full dari bot:**
`/proxy` = status (switch, warp-cli, IP via proxy vs langsung);
`/proxy on|off` + restart server; `/rotate` = ganti IP egress (lapor
lama → baru, aman tanpa sudo); `/limits` = hit rate-limit per model +
tips. Kena 429 saat turn → pesan error otomatis bawa saran
`/rotate`·`/model`·`/limits`. Kuota tiap model terpisah.

Voice note ditranskrip otomatis bila ada STT (whisper CLI, `GROQ_API_KEY`,
atau `OPENAI_API_KEY`); kalau tidak ada, path audio diteruskan ke agent.
**Foto/dokumen dilampirkan sebagai vision/file asli** (`files.uri`) —
model yang support vision (terbukti: `muse-spark`, `mimo-v2.6-flash`)
benar-benar MELIHAT gambar. Bila model menolak gambar, gateway otomatis
retry sekali pakai `vision.fallback_model` (model/sesi kamu tak diubah);
tanpa fallback, jawaban disertai saran `/model` yang support vision.
Grup: `observe_unmentioned_group_messages: true` menyimpan chat biasa
sebagai konteks tanpa menjalankan agent; `ignored_threads` +
`exclusive_bot_mentions` + loop guard ala Hermes juga didukung.
`group_allow_from` (`TELEGRAM_GROUP_ALLOWED_USERS`): sender yang boleh
pakai bot **di grup saja** tanpa akses DM.

Parity Hermes lain: **inline picker** (`inline_mode: true` + `/setinline`
di BotFather, ketik `@bot <cari>`), **local Bot API**
(`base_url`/`base_file_url`, limit file 20MB → 2GB), **notifikasi**
(`important` senyap saat progres / `all`), **cron ke topic**
(`cron_thread_id`), silence token `[SILENT]`/`NO_REPLY`.
**Batching pesan masuk** (`batching.hold_sec`, default 4 dtk): pecahan
pesan panjang yang dikirim beruntun digabung jadi SATU turn (reply nyantol
ke pecahan pertama); `/new`·`/stop`·dkk membuang buffer. Preview streaming
dipotong di batas paragraf + "…".

## Tampilan balasan (gaya Hermes)

Sesi jalan → **dua bubble** persis Hermes:

- **Bubble progres** (pesan terpisah, senyap): tool terminal jadi header +
  blok `<pre>` (header tak diulang untuk call berurutan), tool lain
  single-line persis Hermes — pending `💻 bash...`, selesai
  `💻 Running "date +%Y"`, `📖 Reading "src/x.py"`,
  `🔍 Searching the web for "..."`, `🧩 skill: "pdf"`,
  `🤖 Delegating "..."`, `📋 Updating tasks` (preview 40 char).
- **Bubble jawaban**: preview `💭 Thinking…` (senyap) yang selalu
  **reply ke pesanmu** (klik-reply, DM maupun grup — kayak bot Hermes),
  streaming plain, final di-render **HTML Telegram** + footer,
  **tanpa tool block** (tools sudah di bubble progres). Hasil `/bg` dan
  approve juga nyantol ke pesan pemicu. Matikan via
  `reply_to_trigger: false`.
  Tabel → grup **heading + bullets** persis Hermes (`**Budi**` +
  `• Umur: 20`); tabel dalam code fence dibiarkan; `||spoiler||`, link
  berparens, code ber-tag bahasa didukung; gagal parse → fallback
  plain; panjang → halaman bersufiks `(1/3)` dengan `<pre>` disambung
  rapi; file `MEDIA:/path` setelah teks.
- flood control 429: tunggu `retry_after` lalu retry sekali, tak ada pesan
  ganda; `/footer on|off` toggle footer; `/reasoning on` tampilkan thinking
  (blockquote) bila model memberinya
- **Approval card**: prompt berbahaya memunculkan kartu + tombol
  ✅ Approve / ❌ Deny (bisa juga via teks `/approve` · `/deny`)
- Grup: pesan pemicu di-tag `[nick|id]`, konteks observasi ditandai
  eksplisit sebagai konteks (bukan instruksi) ala Hermes
- `/restart` → sesudah boot bot kirim "✅ Gateway restarted — sesi lanjut."
  ke chat peminta (persis bot gateway lain)

Contoh footer:

```
ling-3.1-flash-free · 5% · ~/oc-workspace · 7s
```

- **Silence token**: kalau agent menjawab persis `[SILENT]`/`NO_REPLY`, gateway
  sengaja tidak mengirim apa-apa (buat automation).
- Voice/foto/file diteruskan ke agent (marker `[The user sent a ...]`), dan
  agent bisa membalas file via tag `MEDIA:/path`.

## Sesi & topic

- DM biasa → 1 sesi per user.
- Group dengan **Topics** aktif → tiap topic dapat sesi sendiri.
- `/new` cuma mereset sesi di chat/topic itu.

## Multi-profile routing

Routing beda chat ke workspace/model berbeda — edit `config.json`:

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

## Kirim file balik ke Telegram

Tiga lapis (otomatis semua, setelah teks):

1. **Tag eksplisit** — agent tulis `MEDIA:/path` (absolut atau relatif ke
   workspace, tanda baca ujung diabaikan):
   ```
   laporan sudah jadi, ini filenya
   MEDIA:/home/ubuntu/oc-workspace/laporan.pdf
   ```
2. **Auto-attach file buatan turn** — file baru/berubah selama turn yang
   disebut di jawaban (path/basenamenya) langsung dilampirkan meski tanpa
   tag (maks 5/turn). Aturan mainnya ada di `oc-workspace/AGENTS.md` yang
   dibaca agent (jawab Indonesia, jangan tempel biner ke teks).
3. **Guard**: video via `sendVideo` (+streaming), tolak >48MB dengan pesan
   jelas, path hilang juga dilaporkan (tidak diam).

## Webhook mode (opsional, buat deploy cloud)

Default long-polling cocok buat VPS. Kalau butuh webhook:

```json
"webhook": {"enabled": true, "url": "https://domain-lu/telegram", "secret": "hasil-openssl-rand-hex-32", "port": 8443}
```

## Keamanan — BACA INI

1. **Agent punya akses penuh server**: shell, baca/tulis file (default `--auto`).
   Siapa pun yang bisa chat ke bot = bisa ngendalikan server. Makanya:
   - `allowed_users` WAJIB diisi. Kalau kosong, semua pesan ditolak.
   - Untuk group, isi `group_allowed_chats`.
2. Token bot jangan dishare — kalau bocor, `/revoke` di BotFather.
3. `config.json` di-`chmod 600`.
4. Ingin lebih aman? Buat user Linux khusus (mis. `ocbot`) dengan akses terbatas,
   lalu jalankan service sebagai user itu, dan arahkan `workspace` ke folder user tsb.
5. Kalau nggak mau agent auto-jalanin perintah berisiko, set
   `auto_approve: false` — tapi request yang butuh izin akan menggantung
   (beda dari Hermes yang punya `/approve` interaktif).

## Troubleshooting

| Gejala | Cek |
|---|---|
| Bot bisu | `systemctl status oc-telegram`, `tail gateway.log` |
| 401 Unauthorized | token salah |
| "akses ditolak" | user ID ≠ isi `allowed_users` |
| Nggak jalan di group | Group Privacy OFF + masuk ulang bot + isi `group_allowed_chats` |
| Balasan terpotong | normal, dibagi per 4000 karakter |
| Agent lambat | `timeout_sec` di profil; cek `opencode` & provider |

## File

```
gateway.py    # entry point: main/polling/webhook (115 baris)
core.py       # config/state/log/RUNTIME (425) — tanpa import modul lain
tg.py         # transport Telegram + send/edit HTML (277)
render.py     # rendering jawaban ala Hermes (307)
pipeline.py   # antrean/run_agent/cron/STT/loop-guard (597)
commands.py   # semua command + tombol inline (912)
dispatch.py   # routing update: gate grup/inline/callback (240)
executor.py   # client HTTP API OpenCode (516)
config.json   # profil/routing/proxy (TANPA rahasia)
.env          # token + ID (chmod 600, dimuat service & loader)
.env.example  # contoh .env
state.json    # sesi & model override (auto)
gateway.log   # log
~/.cache/oc-gateway/                  # voice/foto/dokumen yang diunduh
/etc/systemd/system/oc-telegram.service  # (+ EnvironmentFile .env)
```

---

## Arsitektur (v4 — API asli OpenCode)

```
Telegram ──polling──► gateway.py ──HTTP──► opencode serve (privat :4097)
                          │                    (di-spawn dgn env proxy WARP →
                          │                     trafik agent keluar lewat IP
                          │                     WARP; IP asli VPS aman)
                          └── HTTP API asli OpenCode
```

Gateway **tidak** spawn `opencode run` lagi — dia ngobrol pakai **API asli**
OpenCode lewat server privat yang dia kelola (port 4097, password acak di
`.server_password`, chmod 600).

| Command | Endpoint OpenCode asli |
|---|---|
| kirim pesan | `POST /api/session/{id}/prompt` |
| `/new` | `POST /api/session` |
| `/compact` | `POST /api/session/{id}/compact` |
| `/stop` | `POST /api/session/{id}/interrupt` |
| `/undo` | `DELETE /api/session/{id}/revert` |
| `/approve` `/deny` | `POST /api/session/{id}/permission/{rid}/reply` |
| `/bg` | `POST /api/session/{id}/background` |
| `/btw` | `POST /api/session/{id}/fork` |
| `/usage` | `GET /api/session/{id}` (token asli) |
| `/model` | `POST /api/session/{id}/model` + picker tombol |
| `/agents` `/agent` | `GET /api/agent` + `POST /api/session/{id}/agent` |
| `/sessions` | `GET /api/session?search=` |
| `/commands` | `GET /api/command` (command asli OpenCode: init, review) |
| `/run <nama>` | `POST /api/session/{id}/command` |
| `/init` `/review` | `POST /api/session/{id}/command` (native) |
| `/skills` `/mcp` `/auth` `/plugins` | mirror endpoint |
| `/diff` `/export` | `GET .../diff` · `GET .../export` |

File tambahan: `executor.py` (client API + manajemen server privat).
