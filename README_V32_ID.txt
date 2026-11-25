NEON OS V32 — MULTI-HOST EDITION (REPLIT + LINUX/PaaS)
========================================================

ISI PAKET UTAMA
- bot.py                 Bot Telegram multi-token + FTP failover + downloader + AI opsional
- neon_gateway.py        Gateway API, supervisor/restart bot, Cloudflare Quick Tunnel opsional
- run.sh                 Instal dependency otomatis lalu jalankan Gateway (Linux/Replit)
- setup_env.sh           Membuat .env dari template tanpa menimpa file yang sudah ada
- .env.example           Template lengkap seluruh konfigurasi; semua credential sengaja kosong
- Dockerfile             Deploy container pada Railway dan platform Docker lain
- render.yaml            Blueprint deploy Render
- Procfile               Start command untuk platform yang membaca Procfile
- hosting_patch/         Receiver PHP dan patch integrasi dashboard PHP

A. SUSUNAN SECRETS / ENVIRONMENT VARIABLES
Masukkan nama variabel yang sama dengan .env.example ke menu Secrets/Environment Variables.
Jangan masukkan tanda kutip tambahan. Nilai rahasia jangan ditempel ke chat.

WAJIB UNTUK BOT:
  BOT_TOKEN atau BOT_TOKENS       Token bot Telegram dari BotFather
  OWNER_ID                        ID angka Telegram admin/owner

OPSIONAL:
  BOT_TOKEN_2, BOT_TOKEN_3        Bot Telegram kedua/ketiga
  GROQ_API_KEY                    AI Groq
  FTP_HOST/USER/PASS/PORT         FTP slot 1
  FTP2_HOST ... FTP10_PORT        Slot FTP tambahan sampai 10
  *_COOKIES_FILE                  Path file cookies yang diunggah ke project

WAJIB UNTUK KONTROL REMOTE:
  NEON_API_KEY                    Secret unik acak minimal 32 karakter
  NEON_AUTO_START_BOT=1
  NEON_AUTO_TUNNEL=1              Khusus Replit/host yang punya cloudflared

KONFIGURASI LAIN ADA DI .env.example. Replit Secrets/environment variables menang;
.env menjadi fallback. Nilai Secret kosong juga akan jatuh ke nilai .env.

B. REPLIT
1. Import ZIP ke Replit.
2. Buka Secrets dan isi BOT_TOKEN, OWNER_ID, NEON_API_KEY, serta kredensial lain.
3. Klik Run. run.sh memasang dependency dan menjalankan Gateway.
4. Gateway yang menjalankan bot.py. Jangan jalankan bot.py secara manual bersamaan.
5. Untuk PHP auto-sync, ikuti bagian D.

C. PLATFORM LAIN
Paket tidak terkunci ke Replit. Gateway bind ke 0.0.0.0 dan membaca PORT yang diberikan platform.

RENDER:
1. Push/extract project ke repository Git yang dihubungkan ke Render.
2. Buat Blueprint dari render.yaml atau Web Service Python.
3. Build: pip install -r requirements.txt
   Start: python neon_gateway.py
4. Tambahkan Environment Variables seperti BOT_TOKEN, OWNER_ID, NEON_API_KEY.
5. Set NEON_AUTO_TUNNEL=0. Setelah domain HTTPS tersedia, set:
   NEON_PUBLIC_BASE_URL=https://nama-service.onrender.com
6. Health check: /health. Catatan: paket free dapat sleep dan tidak menjamin 24/7.

RAILWAY / DOCKER:
1. Deploy repository dengan Dockerfile (Railway biasanya mendeteksi otomatis).
2. Set Variables: BOT_TOKEN, OWNER_ID, NEON_API_KEY, NEON_AUTO_START_BOT=1,
   NEON_AUTO_TUNNEL=0, NEON_PUBLIC_BASE_URL=https://domain-publik-anda.
3. Generate domain HTTPS pada dashboard provider. Pastikan service expose port dari PORT.

VPS / LINUX:
1. Install Python 3.11+ dan git/unzip.
2. Jalankan: bash setup_env.sh
3. Edit .env (chmod 600 sudah diterapkan), isi token dan konfigurasi.
4. Jalankan: bash run.sh
5. Untuk 24/7 gunakan systemd/supervisor milik VPS; jangan mengandalkan sesi SSH.

PENTING: tidak semua shared PHP hosting bisa menjalankan Python worker permanen.
Gunakan platform yang mendukung Python web service/container/background process.
Cloudflare Quick Tunnel hanya diperlukan jika host tidak memberi domain publik; pada
Render/Railway, gunakan domain HTTPS provider dan matikan NEON_AUTO_TUNNEL.

D. INTEGRASI PHP HOSTING (OPSIONAL, SATU KALI)
1. Upload hosting_patch/gateway_sync.php ke folder yang sama dengan config.php dan neon_runtime.php.
2. Tambahkan konstanta dari hosting_patch/config_addition.php.txt ke config.php.
3. Isi secret yang sama pada PHP dan Environment Variable NEON_HOSTING_SYNC_TOKEN.
4. Set NEON_HOSTING_SYNC_URL=https://domain-php-anda/gateway_sync.php.
5. Set NEON_API_KEY sama dengan key yang dipakai api.php PHP.
6. Terapkan hosting_patch/api_gateway_url_patch.php.txt pada fungsi gateway_url() di api.php.
7. Pada Replit URL Quick Tunnel disinkronkan otomatis. Pada PaaS, URL dari
   NEON_PUBLIC_BASE_URL disinkronkan otomatis saat Gateway mulai.

E. VALIDASI / TROUBLESHOOTING
- Bot tidak login: cek BOT_TOKEN dan OWNER_ID; jangan ada spasi di awal/akhir.
- FTP gagal: cek host/domain FTP, username, password, port 21 dan izin FTP; beberapa host
  memblokir koneksi FTP dari cloud. Coba FTPS/SFTP hanya jika bot/provider mendukungnya.
- AI mati: cek GROQ_API_KEY, kuota provider, model dan koneksi keluar.
- Port gagal: jangan set NEON_GATEWAY_PORT manual pada PaaS kecuali provider meminta; Gateway
  otomatis membaca PORT. BOT_WEB_PORT terpisah agar tidak bentrok dengan Gateway.
- Tunnel tidak muncul di Render/Railway: normal bila NEON_AUTO_TUNNEL=0; pakai domain HTTPS.
- Lihat log: logs/bot.log, logs/gateway.log, logs/cloudflared.log.
- Invalid integer pada konfigurasi kini memakai default dan memberi peringatan, bukan crash.

BATASAN JUJUR
- Source dan konfigurasi diperiksa statis; tidak ada login/test live pada akun Replit,
  Render, Railway, Telegram, FTP, Groq, Cloudflare, atau PHP hosting pengguna.
- Free hosting bisa sleep, membatasi proses/background worker, bandwidth, atau jam runtime.
  Auto-restart hanya bekerja selama Gateway/container masih hidup; tidak bisa menyalakan
  akun dibanned, service dihentikan, atau mesin yang sedang sleep.
- Shared hosting PHP biasa umumnya tidak bisa menjalankan bot Python jangka panjang.
- AI tidak menulis/mengeksekusi patch kode arbitrer. Recovery otomatis di sini adalah restart
  proses bot; diagnosis ditulis ke log.
- Jangan commit .env, cookies, database, atau secret. Rotasi kredensial lama yang pernah
  terekspos dan jangan pernah mengirim token/password/cookies ke chat.

PEMERIKSAAN BUILD
Python compile, shell syntax, PHP lint, dan ZIP integrity diperiksa setelah perubahan.
Pemeriksaan ini bukan bukti integrasi live pada layanan hosting.
