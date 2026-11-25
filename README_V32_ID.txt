NEON OS V32 — REPLIT REMOTE CONTROL EDITION
============================================

ISI PAKET
- bot.py                 NEON OS bot (basis Replit V31.1)
- neon_gateway.py        Gateway + satu-satunya supervisor bot + tunnel + URL sync PHP
- run.sh                 bootstrap venv, install Python requirements, start Gateway
- replit.nix             meminta Python 3.11 dan cloudflared melalui Nix
- requirements.txt       dependency bot dan Gateway
- .env.example           template konfigurasi; isi rahasia di Replit Secrets
- hosting_patch/         receiver PHP dan patch integrasi ke dashboard/monitor hosting

CARA START REPLIT
1. Buat/import project Replit dari ZIP ini.
2. Buka Secrets (ikon gembok). Isi token bot, OWNER_ID, FTP, AI dan Gateway.
   Minimal untuk menguji Gateway:
     NEON_API_KEY = random secret baru minimal 32 karakter
     NEON_AUTO_START_BOT = 1
     NEON_AUTO_TUNNEL = 1
   Isi BOT_TOKEN atau BOT_TOKEN_2/BOT_TOKEN_3 dan OWNER_ID agar bot Telegram dapat login.
3. Klik Run. run.sh membuat .venv dan memasang requirements otomatis.
   Gateway menjalankan bot.py. JANGAN jalankan bot.py terpisah agar tidak dobel proses.
4. Tunggu log CLOUDFLARE QUICK TUNNEL READY. Kalau cloudflared belum ditemukan,
   cek replit.nix sudah terpakai lalu restart Replit environment sekali.

KONFIGURASI PHP HOSTING (SATU KALI)
1. Upload hosting_patch/gateway_sync.php ke folder yang sama dengan config.php,
   neon_runtime.php, dan monitor_worker.php (biasanya htdocs).
2. Di config.php tambahkan baris dari hosting_patch/config_addition.php.txt.
   Buat secret random sendiri minimal 32 karakter.
3. Di Replit Secrets isi:
     NEON_HOSTING_SYNC_URL = https://DOMAIN-HOSTING-LO/gateway_sync.php
   Hapus spasi pada URL; contoh bentuk: https://domain-anda.com/gateway_sync.php
     NEON_HOSTING_SYNC_TOKEN = nilai secret yang sama dengan config.php
     NEON_API_KEY = nilai yang sama dengan NEON_API_KEY pada config.php hosting
4. Di api.php dashboard aktif, ganti fungsi gateway_url() sesuai
   hosting_patch/api_gateway_url_patch.php.txt. Jangan menghapus header X-API-Key.
5. Jalankan ulang Replit. Gateway akan mengirim URL Quick Tunnel baru ke PHP.
   PHP menyimpan URL ke neon_runtime_dir()/gateway_url.txt; monitor_worker.php yang
   sudah ada membaca file itu. URL otomatis diperbarui setiap tunnel berubah.
6. Buka dashboard PHP, refresh status. Jika masih memakai URL session lama,
   logout/login atau hapus session dashboard lalu refresh.

KONFIGURASI BOT
- 3 bot: BOT_TOKEN / BOT_TOKEN_2 / BOT_TOKEN_3 (atau BOT_TOKENS dipisah koma).
- 10 FTP: FTP_HOST/USER/PASS/PORT untuk slot 1, FTP2_* sampai FTP10_*.
- FTP upload target: REMOTE_DOWNLOAD_DIR=htdocs/downloads.
- AI: GROQ_API_KEY dan GROQ_MODEL (opsional; sesuai provider/model yang tersedia).
- Cookies: upload file cookies yang memang milik/diizinkan untuk digunakan; isi path
  variabel *_COOKIES_FILE di Secrets. Jangan tempel isi cookies ke chat.
- Replit Secrets memiliki prioritas; .env hanya fallback jika Secret kosong/tidak ada.

PENTING / BATASAN JUJUR
- ZIP ini sudah dipaketkan dan diperiksa secara statis, tetapi belum diuji live di akun
  Replit maupun hosting PHP milik Anda. Sinkronisasi baru aktif setelah langkah PHP di atas.
- PHP hosting tidak dapat membangunkan Replit yang dibanned, dihentikan, atau runtime
  yang tidur. Replit harus tetap mengizinkan Shell/Run dan proses Gateway harus hidup.
- Free hosting/Replit tidak menjamin uptime 24/7. Auto-restart menangani proses bot/tunnel
  yang mati selama Gateway masih berjalan; tidak bisa menghidupkan mesin yang sudah mati.
- AI tidak menjalankan patch kode arbitrer. Pemulihan otomatis dibatasi pada restart bot
  yang diizinkan; diagnosis dan log ditampilkan untuk tindakan lanjutan.
- Jangan masukkan secret ke README, source code, screenshot, atau chat. Rotasi kredensial
  yang pernah terekspos: Telegram token, NEON_API_KEY, AI key, password dashboard,
  monitor/sync token, dan FTP password terkait.

VALIDASI YANG DILAKUKAN SAAT PEMBUATAN
- Python compile bot.py dan neon_gateway.py
- Shell syntax check run.sh
- PHP lint gateway_sync.php (jika PHP CLI tersedia di lingkungan build)
- Pemeriksaan isi ZIP dan file konfigurasi
- Tidak termasuk tes login Telegram, FTP, AI provider, Cloudflare, atau koneksi PHP live.
