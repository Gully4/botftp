# NEON OS V26.2 — Replit Multi-Device / Multi-Bot / Multi-FTP

Paket ini dibangun dari source `bot.py` V26.0 yang tersedia di percakapan. Penyesuaian utama menghapus pembatas satu token dan memulihkan mode multi-bot, mempertahankan fitur/handler yang ada di source tersebut, dan menyiapkan konfigurasi hingga 3 bot Telegram, 10 slot akun FTP, satu Gemini API key, serta satu file cookies Instagram.

## Fitur/config yang dipertahankan dari source
- 84 pendaftaran `CommandHandler` yang ada pada source dasar.
- Downloader berbasis `yt-dlp` dan `gallery-dl` serta konfigurasi cookies per platform.
- Upload/arsip ke FTP dengan failover antar akun yang dikonfigurasi.
- Backup ZIP, pencarian/sinkronisasi FTP, kuota, daftar file, dan status FTP.
- Gemini AI, SQLite untuk riwayat AI, log rotasi, health endpoint, dan guardian restart per bot.
- Konfigurasi owner/allowed users dan fungsi admin yang ada pada source dasar.

> Pemeriksaan sintaks/static bukan bukti semua fitur berhasil saat runtime. Uji nyata Telegram, setiap FTP, Gemini, cookies, dan downloader tetap perlu dilakukan.

## Cara pasang di Replit
1. Buat salinan project lama terlebih dahulu agar bisa rollback.
2. Unggah isi ZIP ini ke project Replit.
3. Buka Secrets / Environment Variables. Jangan mengunggah `.env` ke repositori publik.
4. Tambahkan token Telegram dengan **satu** metode:
   - `BOT_TOKENS` = `TOKEN_1,TOKEN_2,TOKEN_3`, atau
   - `BOT_TOKEN_1`, `BOT_TOKEN_2`, `BOT_TOKEN_3`.
   Source juga mendukung `BOT_TOKEN` dan nama alternatif `TELEGRAM_BOT_TOKEN*`. Hindari mengisi beberapa metode dengan token berbeda tanpa sengaja.
5. Isi `OWNER_ID` dengan ID Telegram numerik milik owner, lalu `ALLOWED_USER_IDS` jika ingin mengizinkan user lain.
6. Isi akun FTP yang dipakai: `FTP_HOST`, `FTP_USER`, `FTP_PASS`, `FTP_PORT`; akun tambahan menggunakan `FTP2_HOST`... sampai `FTP10_*`. Slot yang tidak dipakai boleh kosong.
7. Isi `GEMINI_API_KEY`.
8. Upload file cookies Instagram milik akun sendiri/yang diizinkan ke root project bernama `instagram_cookies.txt`. Jangan tempelkan isi cookies ke chat atau repo publik.
9. Di Shell jalankan `pip install -r requirements.txt`.
10. Jalankan `bash run.sh` sekali saja, atau gunakan tombol Run yang memakai `.replit`. Jangan menjalankan `python bot.py` kedua kalinya bersamaan.

## Multi-device dan tiga bot
- Pengguna bisa mengakses bot dari perangkat masing-masing; identitas pengguna/chat digunakan oleh fitur yang menyimpan riwayat AI.
- Ketiga bot berbagi konfigurasi FTP, Gemini, cookies, dan basis data di satu proses. Satu token harus hanya dipakai satu proses polling.
- Sebelum dipakai ramai-ramai, uji tiap bot secara terpisah lalu uji dua pengguna mengirim perintah bersamaan. Beberapa file state lama mungkin berbasis file global; bila ditemukan benturan, perlu audit alur fitur spesifik.

## Batasan penting
- Replit Shell/Free tidak menjamin proses hidup 24 jam. `start.sh` mengulang program setelah crash hanya selama workspace masih berjalan; health endpoint bukan cara melewati batas hosting.
- `/battery` tidak bisa membaca baterai HP dari server Replit.
- FTP failover berarti mencoba akun yang dikonfigurasi sesuai urutan; itu tidak menggabungkan kuota penyimpanan semua FTP menjadi satu storage virtual.
- Platform media bisa mengubah API/challenge; cookies aktif tidak menjamin semua post dapat diunduh.
- `/secret_exec` dinonaktifkan secara default dan hanya bisa diaktifkan dengan `ENABLE_SECRET_EXEC=1`; jangan aktifkan jika tidak benar-benar dibutuhkan.
- Jangan kirim file `.env`, token, password FTP, API key, atau cookies saat meminta bantuan.

## File
- `bot.py`: source utama.
- `requirements.txt`: dependensi Python.
- `.replit`: menjalankan `start.sh`.
- `start.sh`: launcher/restart dengan log di `logs/`.
- `.env.example`: daftar variabel konfigurasi tanpa rahasia.

## Perbaikan koneksi SSL Replit (V26.4)

`start.sh` kini mengatur `SSL_CERT_FILE` dan `REQUESTS_CA_BUNDLE` ke bundel CA Certifi bila tersedia, tanpa mematikan verifikasi sertifikat. Dependensi `certifi` dan `httpx` juga dicantumkan eksplisit.

Jika masih muncul `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`, kemungkinan ada sertifikat/proxy di lingkungan runtime yang tidak dipercaya oleh bundel CA standar. Jangan gunakan `verify=False`; periksa jaringan/runtime Replit dan log terbaru di `logs/bot.log` serta `logs/runner.log`.

### Perbaikan koneksi SSL Telegram (V26.4)

Launcher `run.sh` meneruskan ke `start.sh`, yang memilih CA bundle dari `certifi` dan mengatur `SSL_CERT_FILE` sebelum bot dimulai. Jalankan bot melalui `bash run.sh` agar konfigurasi SSL ikut diterapkan. Verifikasi SSL tetap aktif.
