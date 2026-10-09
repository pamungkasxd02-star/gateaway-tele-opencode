# gateaway-tele-opencode

Bot Telegram yang menjalankan [OpenCode](https://opencode.ai) di VPS.
Chat dari Telegram (DM / grup / forum topic) dieksekusi sebagai prompt
OpenCode di server ini, hasilnya dibalas ke Telegram.

```
Telegram ──polling──► gateway.py ──HTTP──► opencode serve (privat :4097)
```

## Kebutuhan

- VPS Ubuntu/Debian (atau distro dengan systemd), akses sudo
- Python 3.10+ (stdlib saja, tanpa dependency pip) + `curl`
- OpenCode CLI v2 terpasang (`opencode --version` jalan) dan provider
  sudah login (`opencode auth list` — tanpa ini agent tidak bisa jawab)
- `git` (untuk clone repo ini)
- Akun Telegram

Opsional:

- `warp-cli` (Cloudflare WARP) — untuk `/proxy` dan `/rotate`
- Salah satu untuk transkrip voice note: CLI `whisper`, atau
  `GROQ_API_KEY`, atau `OPENAI_API_KEY`. Tanpa ketiganya, audio
  diteruskan apa adanya sebagai file.

## Instal dari nol

```bash
# 1. clone
git clone https://github.com/pamungkasxd02-star/gateaway-tele-opencode
cd gateaway-tele-opencode

# 2. isi rahasia (jangan commit file ini)
cp .env.example .env
nano .env
chmod 600 .env
```

Isi minimal `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABC...
TELEGRAM_ALLOWED_USERS=123456789
```

Token didapat dari [@BotFather](https://t.me/BotFather) (`/newbot`).
User ID didapat dari [@userinfobot](https://t.me/userinfobot).
Opsional di `.env`: `TELEGRAM_HOME_CHANNEL`,
`TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_GROUP_ALLOWED_USERS`,
`TELEGRAM_CRON_THREAD_ID`, `TELEGRAM_NOTIFICATIONS=all`,
`GROQ_API_KEY`, `OPENAI_API_KEY`.

```bash
# 3. pasang service
sudo cp oc-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oc-telegram
sudo systemctl status oc-telegram

# 4. cek log + tes
tail -f gateway.log
```

Isi `oc-telegram.service` (sudah termasuk di repo):

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

Sesuaikan `User=` dan path dengan mesinmu. Tes: kirim pesan ke bot.

Catatan grup: Bot Settings → *Group Privacy* → **Turn off** di BotFather,
lalu keluarkan dan masukkan ulang bot ke grup, dan isi
`TELEGRAM_GROUP_ALLOWED_CHATS`.

## Cara kerja balasan

Setiap pesan user memicu satu turn agent. Selama turn berjalan ada dua
bubble:

- **Bubble progres** (pesan terpisah, senyap): baris per tool call
  (`💻 Running "date +%Y"`), selesai ditandai, call terminal tampil
  sebagai blok code.
- **Bubble jawaban**: mulai dari `💭 Thinking…`, diedit mengikuti teks
  yang mengalir, selalu me-reply pesan pemicu. Hasil akhir di-render
  sebagai HTML Telegram (bold/italic/code/link/quote/tabel) + footer
  `model · %konteks · ~/cwd · durasi`.

Aturan lain:

- Pesan beruntun (jeda < 4 detik, `batching.hold_sec`) digabung jadi
  satu turn.
- Balasan > 3800 karakter dibagi halaman bersufiks `(1/3)`.
- Jawaban persis `[SILENT]`/`NO_REPLY`/sejenis tidak dikirim (automation).
- Prompt berbahaya memunculkan kartu approval (tombol ✅/❌ atau
  `/approve` · `/deny`).
- Notifikasi progres dimatikan default (`important`); `all` untuk
  bunyikan semua.
- Flood 429: tunggu `retry_after` lalu retry sekali.
- `/restart` menunggu turn aktif selesai (maks 150 detik) lalu kirim
  konfirmasi sesudah boot.

## Command

| Command | Fungsi |
|---|---|
| `/help` | daftar semua command |
| `/start` | bantuan + tampilkan tombol cepat |
| `/keyboard` | tampilkan tombol cepat permanen |
| `/menu` | tombol inline (Models/Sessions/Agents/Status/Cron/Limits/Stats/MCP/Help) |
| `/new` · `/reset` | percakapan baru (sesi chat ini saja) |
| `/retry` | jalankan ulang pesan terakhir |
| `/undo` | batalkan exchange terakhir |
| `/compress` · `/compact` | padatkan konteks |
| `/title [nama]` · `/rename` | judul sesi |
| `/resume [nama]` | lanjutkan sesi bernama |
| `/sessions` · `/session id` | daftar / pindah sesi |
| `/stop` | hentikan turn yang jalan |
| `/bg <prompt>` | jalan di background, hasil dikirim lagi |
| `/btw <tanya>` | pertanyaan sampingan (sesi cabang, dihapus lagi) |
| `/branch [nama]` | fork sesi, chat pindah ke cabang |
| `/model [provider:model]` · `/models` | lihat/ganti model |
| `/agents` · `/agent [nama]` | daftar/ganti agent |
| `/personality [nama]` · `/reasoning on\|off` | persona / tampilkan reasoning |
| `/status` · `/usage` · `/context` · `/whoami` | info sesi & token |
| `/stats` · `/insights` | statistik opencode (sama) |
| `/mcp` · `/auth` · `/plugins` · `/update` | mirror CLI opencode |
| `/commands` · `/run <nama>` · `/skills` | command/skill OpenCode |
| `/diff` · `/export` | diff sesi / unduh sesi sebagai file |
| `/init` · `/review [target]` | setup AGENTS.md / review perubahan |
| `/goal <teks>` | standing goal: dikerjakan berputar sampai done |
| `/goal status\|pause\|resume\|clear` · `/subgoal ...` | kelola goal |
| `/loop 5m ... [--times N]` · `/loop status\|stop id` | prompt berulang di sesi ini |
| `/heartbeat every 5m ...` | prompt berkala, hanya saat idle |
| `/queue <prompt>` | antre untuk giliran berikut |
| `/steer <catatan>` | arahkan turn berikut |
| `/plan <tugas>` | tulis rencana ke file, tanpa eksekusi |
| `/cron add <expr> <prompt>` · `/cron list\|rm\|on\|off` | jadwal ke home channel |
| `/proxy [on\|off]` · `/rotate` · `/limits` · `/egress` | WARP + rate limit |
| `/sethome` · `/platforms` | home channel · status gateway |
| `/approve` · `/deny` | setujui/tolak prompt berbahaya |
| `/footer on\|off` · `/config` | footer balasan · lihat config |
| `/restart` | restart gateway (graceful) |
| `/<nama-skill>` | command tak dikenal → jalan sebagai skill agent |

Format cron: `1m|30m|2h|1d` (min 1m), `every 30m`, `daily 07:00`,
atau cron 5-field (`*/15 * * * *`). Butuh `/sethome` dulu supaya hasil
cron ada tujuan. Contoh: `/cron add 30m cek harga BTC lalu ringkas`.

Contoh goal: `/goal perbaiki semua test sampai hijau` — judge menilai
tiap turn (`DONE/CONTINUE/BLOCKED`), lanjut otomatis. Budget default 20
turn (`goals.max_turns`). `/goal pause` kapan saja menghentikan loop.

## File & media

Masuk: voice/audio ditranskrip bila ada STT, kalau tidak diteruskan
sebagai file. Foto dan dokumen dilampirkan sebagai input vision/file
asli ke model. Bila model menolak gambar, dicoba sekali pakai
`vision.fallback_model` tanpa mengubah model/sesimu.

Keluar: teks dulu, lalu lampiran. Agent melampirkan dengan tag
`MEDIA:/path` (relatif ke workspace boleh), atau otomatis: file yang
dibuat/diubah selama turn dan disebut di jawaban ikut terlampir
(maks 5/turn, maks 48MB/file). Aturan untuk agent ada di
`oc-workspace/AGENTS.md`.

Grup: tanpa mention, bot diam (butuh `require_mention` + privacy OFF).
`observe_unmentioned_group_messages: true` menyimpan obrolan biasa
sebagai konteks tanpa menjalankan agent. `group_allow_from`
(`TELEGRAM_GROUP_ALLOWED_USERS`) mengizinkan sender tertentu hanya di
grup, tanpa akses DM. `ignored_threads` membisukan topic tertentu.

`/setinline` di BotFather + `inline_mode: true` mengaktifkan picker:
ketik `@namabot <cari>` di chat mana pun untuk cari command/skill.
`base_url`/`base_file_url` menunjuk ke server Bot API lokal (limit file
20MB → 2GB).

## Multi-profile routing

Chat/thread berbeda bisa memakai workspace/model/timeout berbeda —
edit `config.json`:

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

## Webhook (opsional)

Default long-polling (cocok untuk VPS always-on). Untuk deploy cloud
yang bangun saat ada traffic masuk:

```json
"webhook": {"enabled": true, "url": "https://domain-kamu/telegram", "secret": "hasil-openssl-rand-hex-32", "port": 8443}
```

## Keamanan — baca ini

Siapa pun yang bisa chat ke bot bisa mengeksekusi perintah di server
(agent punya akses shell dan file). Karena itu:

1. `TELEGRAM_ALLOWED_USERS` wajib diisi. Kosong = semua pesan ditolak.
2. Token bot jangan disebar. Bocor → `/revoke` di BotFather, ganti
   `.env`, restart service.
3. `config.json` dan `.env` di-`chmod 600`. Keduanya tidak masuk git
   (yang masuk repo: `config.json` tanpa rahasia — token cukup
   `${TELEGRAM_BOT_TOKEN}`).
4. Mau isolasi lebih? Jalankan service sebagai user Linux khusus dengan
   akses terbatas dan arahkan `workspace` ke folder user itu.

## Troubleshooting

| Gejala | Cek |
|---|---|
| Bot bisu | `systemctl status oc-telegram`, `tail gateway.log` |
| 401 Unauthorized | token salah di `.env` |
| "akses ditolak" | user ID tidak ada di `TELEGRAM_ALLOWED_USERS` |
| Tidak jalan di grup | Group Privacy OFF + bot keluar-masuk ulang + `TELEGRAM_GROUP_ALLOWED_CHATS` |
| Suggest `/` tidak muncul | force-close aplikasi Telegram, ketik `/` saja (huruf memfilter daftar) |
| "Thinking…" lama | model lambat — `/stop`, ganti `/model`, atau `/compress`/`/new` bila konteks bengkak |
| Balasan panjang terpecah | normal — halaman `(1/3)`, file setelah teks |

## File dalam repo

```
gateway.py    # entry point: main/polling/webhook
core.py       # config/state/log
tg.py         # transport Telegram
render.py     # render jawaban jadi HTML Telegram
pipeline.py   # antrean turn, cron/loop/heartbeat, STT, goal engine
commands.py   # semua command + tombol
dispatch.py   # routing update Telegram
executor.py   # client HTTP API OpenCode + server privat :4097
config.json   # profil/routing (tanpa rahasia)
.env.example  # contoh .env
oc-telegram.service  # unit systemd
```

Runtime (tidak ikut repo): `.env`, `state.json`, `gateway.log`,
`~/.cache/oc-gateway/` (media terunduh).

## Arsitektur

Gateway tidak spawn `opencode run` — ia mengelola server OpenCode
privat sendiri (port 4097, password acak di `.server_password`) dan
memakai HTTP API aslinya:

| Command | Endpoint |
|---|---|
| kirim pesan (+ file) | `POST /api/session/{id}/prompt` |
| `/new` | `POST /api/session` |
| `/compress` | `POST /api/session/{id}/compact` |
| `/stop` | `POST /api/session/{id}/interrupt` |
| `/undo` | `DELETE /api/session/{id}/revert` |
| `/approve` `/deny` | `POST /api/session/{id}/permission/{rid}/reply` + gate regex lokal |
| `/btw` | `POST /api/session/{id}/fork` |
| `/usage` `/context` | `GET /api/session/{id}` (token asli) |
| `/model` | `POST /api/session/{id}/model` |
| `/sessions` | `GET /api/session` |
| `/init` `/review` via `/run` | `POST /api/session/{id}/command` |
