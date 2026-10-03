import os
import logging
import random
import time
import html
import gc
import zipfile
import urllib.request
import asyncio
import json
from datetime import datetime
from ftplib import FTP
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# 1. Load Environment Variables dari .env
load_dotenv()

BOT_VERSION = "v6.0 Cyber Core Edition (Multi-Bot Engine)"

# ==================== BANNER & LOGGING TERMUX ====================
def show_termux_banner():
    banner = f"""
\033[1;36m
███████╗████████╗██████╗     ██████╗ ██████╗ ██████╗ ███████╗
██╔════╝╚══██╔══╝██╔══██╗    ██╔══██╗██╔══██╗██╔══██╗██╔════╝
█████╗     ██║   ██████╔╝    ██║  ██║██████╔╝██████╔╝███████╗
██╔══╝     ██║   ██╔═══╝     ██║  ██║██╔══██╗██╔═══╝ ╚════██║
██║        ██║   ██║         ██████╔╝██║  ██║██║     ███████║
╚═╝        ╚═╝   ╚═╝         ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚══════╝
\033[1;33m  [►] CLOUD FTP MULTI-BOT ENGINE - {BOT_VERSION}
  [►] STATUS  : ACTIVE & ONLINE
  [►] SYSTEM  : PYTHON 3 / TERMUX ENVIRONMENT
\033[0m"""
    print(banner)

logging.basicConfig(
    format='\033[1;30m[%(asctime)s]\033[0m \033[1;32m%(levelname)s\033[0m ─ \033[1;37m%(message)s\033[0m',
    level=logging.INFO,
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Config List Token & FTP
raw_tokens = os.getenv("BOT_TOKENS", "")
BOT_TOKENS = [token.strip() for token in raw_tokens.split(",") if token.strip()]

FTP_HOST = os.getenv("FTP_HOST", "ftpupload.net")
FTP_USER = os.getenv("FTP_USER", "if0_43064672")
FTP_PASS = os.getenv("FTP_PASS", "ki2fICWM6nN7m")
FTP_PORT = int(os.getenv("FTP_PORT", 21))

BASE_HTTP_URL = os.getenv("BASE_HTTP_URL", f"http://{FTP_USER}.epizy.com/")

# OWNER_ID: User ID Telegram Pemilik
OWNER_ID = 7169837270  

HISTORY_FILE = "chat_history.json"
ftp_lock = asyncio.Lock()

# ==================== UTILS & HELPERS ====================
def save_chat_history(user_id: int, username: str, full_name: str, message_text: str):
    """Menyimpan log percakapan user ke file JSON lokal"""
    try:
        history_data = []
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history_data = json.load(f)
            except Exception:
                history_data = []

        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id,
            "username": f"@{username}" if username else "NoUsername",
            "full_name": full_name,
            "message": message_text
        }
        
        history_data.append(log_entry)
        
        if len(history_data) > 500:
            history_data = history_data[-500:]

        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Gagal menyimpan riwayat chat: {e}")

def get_user_name(update: Update) -> str:
    user = update.effective_user
    if user and user.first_name:
        return html.escape(user.first_name)
    return "Operator"

def get_respon_santai(user_name: str) -> list:
    return [
        f"⚡ <b>[CYBER CORE]</b> Standby Bos <b>{user_name}</b>! Kirim file langsung untuk disimpan ke Cloud FTP.",
        f"🛡️ <b>[CYBER CORE]</b> Sistem penyimpanan siap tempur 24/7. Ada file yang mau dimasukkan, Bro <b>{user_name}</b>?",
        f"🔥 <b>[CYBER CORE]</b> Koneksi FTP stabil tanpa kendala, Bos <b>{user_name}</b>. Silakan lempar filenya!",
        f"🌐 <b>[CYBER CORE]</b> Siap melayani pengolahan media & berkas, Bro <b>{user_name}</b>!"
    ]

def is_authorized(update: Update) -> bool:
    if OWNER_ID is None:
        return True
    return update.effective_user.id == OWNER_ID

def is_owner(update: Update) -> bool:
    if OWNER_ID is None:
        return True
    return update.effective_user.id == OWNER_ID

def ensure_ftp_dir(ftp, folder_name):
    try:
        ftp.cwd('/')
        try:
            ftp.cwd('htdocs')
        except Exception:
            pass

        try:
            ftp.cwd(folder_name)
        except Exception:
            ftp.mkd(folder_name)
            ftp.cwd(folder_name)
    except Exception as e:
        logger.error(f"Error FTP Navigasi: {e}")

async def delete_msg_safe(msg):
    try:
        await msg.delete()
    except Exception:
        pass

def get_ftp_connection():
    ftp = FTP()
    ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.set_pasv(True)
    try:
        ftp.cwd('htdocs')
    except Exception:
        pass
    return ftp

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 Storage Quota", callback_data='btn_storage'),
            InlineKeyboardButton("📁 Cek Isian FTP", callback_data='btn_list')
        ],
        [
            InlineKeyboardButton("📈 Cyber Stats", callback_data='btn_stats'),
            InlineKeyboardButton("🌴 Tree Directory", callback_data='btn_tree')
        ],
        [
            InlineKeyboardButton("⚡ Command Console", callback_data='btn_help'),
            InlineKeyboardButton("⚙️ System Status", callback_data='btn_about')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== RAHASIA OWNER ====================
async def secret_chat_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    if not os.path.exists(HISTORY_FILE):
        await update.message.reply_text("🕵️‍♂️ <b>[CYBER LOG]</b> Belum ada log percakapan tersimpan.", parse_mode='HTML')
        return

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            await update.message.reply_text("🕵️‍♂️ <b>[CYBER LOG]</b> Log riwayat kosong.", parse_mode='HTML')
            return

        recent_logs = data[-20:]
        text_out = "<b>🕵️‍♂️ [SECRET SYSTEM LOG - LAST 20 CHATS]</b>\n"
        text_out += "═════════════════════════════\n"

        for idx, item in enumerate(recent_logs, 1):
            text_out += (
                f"<b>{idx}. [{item['timestamp']}]</b>\n"
                f"👤 <b>User:</b> {html.escape(item['full_name'])} ({item['username']})\n"
                f"🆔 <b>ID:</b> <code>{item['user_id']}</code>\n"
                f"💬 <b>Payload:</b> <i>{html.escape(str(item['message']))}</i>\n\n"
            )

        await update.message.reply_text(text_out, parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca history: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def secret_clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return

    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
        await update.message.reply_text("🧹 <b>[CYBER LOG]</b> Seluruh log tersembunyi berhasil dibersihkan!", parse_mode='HTML')
    else:
        await update.message.reply_text("ℹ️ Log riwayat sudah kosong.")

# ==================== FITUR UTAMA BOT ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("🚫 <b>[ACCESS DENIED]</b> Sistem dikunci secara privat oleh Owner.", parse_mode='HTML')
        return

    user_name = get_user_name(update)
    bot_info = await context.bot.get_me()
    pesan_menu = (
        f"━━━━━ <b>CYBER STORAGE SYSTEM</b> ━━━━━\n"
        f"<b>BOT ACTIVE:</b> <b>@{bot_info.username}</b>\n"
        f"<b>ENGINE VERSION:</b> <code>{BOT_VERSION}</code>\n"
        f"<b>OPERATOR:</b> <b>{user_name}</b>\n"
        f"<b>STATUS:</b> <code>ONLINE (FTP ACTIVE)</code>\n"
        f"═════════════════════════════\n"
        f"Selamat datang di Control Panel Cloud Storage FTP.\n"
        f"Gunakan menu cepat di bawah ini atau kirim berkas/media secara langsung ke percakapan ini."
    )
    await update.message.reply_text(pesan_menu, parse_mode='HTML', reply_markup=get_main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'btn_storage':
        await storage_quota(update, context)
    elif query.data == 'btn_list':
        await list_ftp(update, context)
    elif query.data == 'btn_stats':
        await quick_stats(update, context)
    elif query.data == 'btn_tree':
        await cloud_tree(update, context)
    elif query.data == 'btn_help':
        await help_command(update, context)
    elif query.data == 'btn_about':
        await about_command(update, context)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    bot_info = await context.bot.get_me()
    pesan = (
        f"⚙️ <b>SYSTEM INFORMATION & SPECS</b>\n"
        f"═════════════════════════════\n"
        f"🤖 <b>Bot Instance:</b> @{bot_info.username}\n"
        f"🤖 <b>Core System:</b> {BOT_VERSION}\n"
        f"👤 <b>Active Operator:</b> {user_name}\n"
        f"💻 <b>Host Environment:</b> Python 3 + Termux Multi-Bot Cluster\n"
        f"🌐 <b>FTP Endpoint:</b> <code>{FTP_HOST}</code>\n"
        f"📡 <b>HTTP Gateway:</b> <code>{BASE_HTTP_URL}</code>\n"
        f"═════════════════════════════\n"
        f"<i>Sistem FTP otomatis berkecepatan tinggi dengan auto-retry timeout handler.</i>"
    )
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(pesan, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    pesan = (
        f"⚡ <b>CONSOLE COMMAND LIST ({BOT_VERSION})</b>\n"
        f"═════════════════════════════\n"
        f"🌐 <b>REMOTING & ARCHIVE</b>\n"
        f"• <code>/sync [link_url]</code> ─ Download direct link HTTP ke Cloud\n"
        f"• <code>/unzip [file.zip]</code> ─ Ekstrak & pilah otomatis file ZIP\n"
        f"• <code>/backup</code> ─ Backup seluruh Cloud FTP ke .ZIP\n"
        f"• <code>/zip [folder]</code> ─ Kompres isi folder ke file .ZIP\n\n"
        f"📁 <b>FILE & DIRECTORY MANAGEMENT</b>\n"
        f"• <code>/list [folder]</code> ─ Cek daftar file dalam folder\n"
        f"• <code>/cloud_tree</code> ─ Tampilan visual pohon direktori\n"
        f"• <code>/get [nama_file]</code> ─ Download file dari Cloud FTP\n"
        f"• <code>/info [nama_file]</code> ─ Detail file & link direct HTTP\n"
        f"• <code>/share [nama_file]</code> ─ Dapatkan URL Direct HTTP\n"
        f"• <code>/search [kata_kunci]</code> ─ Cari file di seluruh folder\n"
        f"• <code>/move [asal] [tujuan]</code> ─ Pindahkan lokasi file\n"
        f"• <code>/rename [lama] [baru]</code> ─ Ubah nama file/folder\n"
        f"• <code>/dupe [file] [baru]</code> ─ Duplikasi file di server\n"
        f"• <code>/find_dupes</code> ─ Pindai file duplikat berulang\n"
        f"• <code>/delete [file]</code> ─ Hapus file dari Cloud FTP\n\n"
        f"🛠️ <b>STORAGE & SYSTEM UTILS</b>\n"
        f"• <code>/mkdir [folder]</code> ─ Buat direktori baru\n"
        f"• <code>/rmdir [folder]</code> ─ Hapus folder kosong\n"
        f"• <code>/bulk_delete [folder]</code> ─ Hapus seluruh isi folder\n"
        f"• <code>/quota</code> ─ Rincian kapasitas memori\n"
        f"• <code>/stats</code> ─ Ringkasan statistik server\n"
        f"• <code>/clean_empty</code> ─ Sapu bersih folder kosong\n"
        f"═════════════════════════════\n"
        f"👤 <b>Operator:</b> {user_name}"
    )
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(pesan, parse_mode='HTML')

async def sync_url_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🌐 <b>Format Salah!</b> Gunakan:\n<code>/sync https://example.com/file.zip</code>", parse_mode='HTML')
        return

    url = context.args[0]
    file_name = os.path.basename(url.split("?")[0]) or f"downloaded_{int(time.time())}"
    local_path = f"temp_sync_{file_name}"

    msg_status = await update.message.reply_text(f"🚀 <b>[CYBER SYNC]</b> Mengunduh berkas dari URL internet...\n<code>{html.escape(url)}</code>", parse_mode='HTML')

    try:
        urllib.request.urlretrieve(url, local_path)
        
        ext = os.path.splitext(file_name)[1].lower()
        category = "Lainnya"
        if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']: category = "Gambar"
        elif ext in ['.mp4', '.mkv', '.avi', '.mov']: category = "Video"
        elif ext in ['.mp3', '.wav', '.ogg']: category = "Audio"
        elif ext in ['.zip', '.rar', '.7z', '.gz']: category = "Arsip_Zip"
        elif ext in ['.pdf', '.docx', '.txt', '.xlsx']: category = "Dokumen"

        async with ftp_lock:
            ftp = get_ftp_connection()
            ensure_ftp_dir(ftp, category)
            
            with open(local_path, 'rb') as fp:
                ftp.storbinary(f"STOR {file_name}", fp)
            ftp.quit()

        await delete_msg_safe(msg_status)
        await update.message.reply_text(
            f"⚡ <b>REMOTE SYNC SUKSES!</b>\n\n"
            f"📄 <b>File:</b> <code>{html.escape(file_name)}</code>\n"
            f"📂 <b>Path:</b> <code>htdocs/{category}/</code>",
            parse_mode='HTML'
        )
    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Remote Sync Gagal:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

async def unzip_cloud_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📦 <b>Format Salah!</b> Gunakan:\n<code>/unzip Arsip_Zip/data.zip</code>", parse_mode='HTML')
        return

    zip_path = context.args[0]
    zip_name = os.path.basename(zip_path)
    local_zip = f"temp_unzip_{zip_name}"
    extract_dir = f"extracted_{int(time.time())}"

    msg_status = await update.message.reply_text(f"📦 <b>[CYBER UNZIP]</b> Mengunduh & memproses ekstraksi file ZIP...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            with open(local_zip, 'wb') as fp:
                ftp.retrbinary(f"RETR {zip_path}", fp.write)

            with zipfile.ZipFile(local_zip, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            uploaded_files = 0
            for root, dirs, files_list in os.walk(extract_dir):
                for file in files_list:
                    file_full = os.path.join(root, file)
                    ext = os.path.splitext(file)[1].lower()
                    
                    cat = "Lainnya"
                    if ext in ['.jpg', '.jpeg', '.png', '.webp']: cat = "Gambar"
                    elif ext in ['.mp4', '.mkv', '.avi']: cat = "Video"
                    elif ext in ['.mp3', '.wav']: cat = "Audio"
                    elif ext in ['.pdf', '.docx', '.txt']: cat = "Dokumen"

                    ensure_ftp_dir(ftp, cat)
                    with open(file_full, 'rb') as fp:
                        ftp.storbinary(f"STOR {file}", fp)
                    uploaded_files += 1

            ftp.quit()
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"🎉 <b>[UNZIP SUCCESS]</b>\nEkstraksi selesai! <code>{uploaded_files}</code> file dipindahkan & dikategorikan otomatis.", parse_mode='HTML')

    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Unzip:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        if os.path.exists(local_zip): os.remove(local_zip)
        if os.path.exists(extract_dir):
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)

async def cloud_tree(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message if update.message else update.callback_query.message
    msg_status = await msg.reply_text("🌴 <b>[CYBER TREE]</b> Menyusun peta direktori cloud...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            tree_text = "<b>🌴 CLOUD DIRECTORY TREE (HTDOCS)</b>\n"
            tree_text += "═════════════════════════════\n"

            for fld in folders:
                tree_text += f"├── 📁 <b>{fld}</b>\n"
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    files = [i for i in ftp.nlst() if i not in ['.', '..']]
                    for idx, file in enumerate(files[:5]):
                        prefix = "└──" if idx == len(files[:5]) - 1 and len(files) <= 5 else "├──"
                        tree_text += f"│   {prefix} 📄 <code>{html.escape(file)}</code>\n"
                    if len(files) > 5:
                        tree_text += f"│   └── <i>...dan {len(files)-5} file lainnya</i>\n"
                except Exception:
                    pass

            ftp.quit()
        await delete_msg_safe(msg_status)
        await msg.reply_text(tree_text, parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await msg.reply_text(f"❌ <b>Gagal Menyusun Tree:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def backup_cloud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    msg_status = await update.message.reply_text("🛡️ <b>[CYBER BACKUP]</b> Membuat arsip penuh dari seluruh file server FTP...", parse_mode='HTML')
    backup_zip = f"Backup_FTP_{user_name}_{int(time.time())}.zip"

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]

            with zipfile.ZipFile(backup_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for fld in folders:
                    try:
                        ftp.cwd(f'/htdocs/{fld}')
                        files = [f for f in ftp.nlst() if f not in ['.', '..']]
                        for f in files:
                            temp_f = f"temp_bk_{f}"
                            with open(temp_f, 'wb') as fp:
                                ftp.retrbinary(f"RETR {f}", fp.write)
                            zipf.write(temp_f, f"{fld}/{f}")
                            if os.path.exists(temp_f): os.remove(temp_f)
                    except Exception:
                        pass

            ftp.quit()
        await delete_msg_safe(msg_status)

        with open(backup_zip, 'rb') as doc:
            await context.bot.send_document(
                chat_id=update.effective_chat.id, 
                document=doc, 
                filename=backup_zip,
                caption=f"🛡️ <b>FULL BACKUP COMPLETED!</b>\nRequested by: <b>{user_name}</b>", 
                parse_mode='HTML'
            )
    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Backup:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        if os.path.exists(backup_zip): os.remove(backup_zip)

async def find_dupes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_status = await update.message.reply_text("🔍 <b>[CYBER DUPES]</b> Memindai file ganda di seluruh direktori...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            file_map = {}
            duplicates = []

            for fld in folders:
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    files = [f for f in ftp.nlst() if f not in ['.', '..']]
                    for f in files:
                        try:
                            sz = ftp.size(f)
                            key = f"{f}_{sz}"
                            if key in file_map:
                                duplicates.append((fld, f, file_map[key]))
                            else:
                                file_map[key] = fld
                        except Exception:
                            pass
                except Exception:
                    pass

            ftp.quit()
        await delete_msg_safe(msg_status)

        if not duplicates:
            await update.message.reply_text("✨ <b>[CLEAR]</b> Tidak ada file duplikat terdeteksi!", parse_mode='HTML')
            return

        pesan = "⚠️ <b>TERDETEKSI FILE DUPLIKAT:</b>\n═════════════════════════════\n"
        for fld, f, orig_fld in duplicates:
            pesan += f"• <code>{f}</code> (Ganda di <b>{orig_fld}</b> & <b>{fld}</b>)\n"

        await update.message.reply_text(pesan, parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Pindai Duplikat:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def quick_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = get_user_name(update)
    msg = update.message if update.message else update.callback_query.message
    msg_status = await msg.reply_text("📈 <b>[CYBER STATS]</b> Menghimpun statistik server...", parse_mode='HTML')
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            total_file_count = 0
            total_folder_count = len(folders)

            for fld in folders:
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    items = ftp.nlst()
                    total_file_count += len([i for i in items if i not in ['.', '..']])
                except Exception:
                    pass

            ftp.quit()
        await delete_msg_safe(msg_status)

        pesan = (
            f"📊 <b>CYBER STORAGE METRICS</b>\n"
            f"═════════════════════════════\n"
            f"📁 <b>Total Kategori:</b> <code>{total_folder_count} Folder</code>\n"
            f"📄 <b>Total Berkas:</b> <code>{total_file_count} File</code>\n"
            f"⚡ <b>Koneksi Engine:</b> <code>STABLE (Passive FTP)</code>\n"
            f"👤 <b>Operator Aktif:</b> <b>{user_name}</b>"
        )
        await msg.reply_text(pesan, parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await msg.reply_text(f"❌ <b>Gagal Memuat Stats:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def duplicate_file_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("📋 <b>Format Salah!</b> Gunakan:\n<code>/dupe Gambar/photo.jpg photo_copy.jpg</code>", parse_mode='HTML')
        return

    src_file = context.args[0]
    new_file_name = context.args[1]
    temp_path = f"dupe_{os.path.basename(src_file)}"

    msg_status = await update.message.reply_text("📋 <b>[CYBER DUPE]</b> Mengcloning berkas di server...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folder = os.path.dirname(src_file)
            
            with open(temp_path, 'wb') as fp:
                ftp.retrbinary(f"RETR {src_file}", fp.write)

            target_path = f"{folder}/{new_file_name}" if folder else new_file_name
            with open(temp_path, 'rb') as fp:
                ftp.storbinary(f"STOR {target_path}", fp)

            ftp.quit()
        await delete_msg_safe(msg_status)

        await update.message.reply_text(f"📋 <b>[CLONE SUCCESS]</b>\nTarget Baru: <code>{html.escape(target_path)}</code>", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Duplikasi:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

async def zip_folder_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📦 <b>Format Salah!</b> Gunakan:\n<code>/zip Gambar</code>", parse_mode='HTML')
        return

    folder_name = context.args[0]
    zip_filename = f"{folder_name}_archive.zip"
    msg_status = await update.message.reply_text(f"📦 <b>[CYBER ZIP]</b> Mengompresi folder '<code>{html.escape(folder_name)}</code>'...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.cwd(f"/htdocs/{folder_name}")
            files = [f for f in ftp.nlst() if f not in ['.', '..']]

            if not files:
                await delete_msg_safe(msg_status)
                await update.message.reply_text(f"📂 Folder <code>{html.escape(folder_name)}</code> kosong!", parse_mode='HTML')
                ftp.quit()
                return

            with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in files:
                    local_f = f"temp_{file}"
                    with open(local_f, 'wb') as fp:
                        ftp.retrbinary(f"RETR {file}", fp.write)
                    zipf.write(local_f, file)
                    if os.path.exists(local_f):
                        os.remove(local_f)

            ftp.quit()
        await delete_msg_safe(msg_status)

        with open(zip_filename, 'rb') as doc:
            await context.bot.send_document(chat_id=update.effective_chat.id, document=doc, filename=zip_filename, caption=f"📦 Archive folder <b>{html.escape(folder_name)}</b> berhasil dibuat!", parse_mode='HTML')

    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Kompresi Zip:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        if os.path.exists(zip_filename):
            os.remove(zip_filename)

async def bulk_delete_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("💥 <b>Format Salah!</b> Gunakan:\n<code>/bulk_delete Gambar</code>", parse_mode='HTML')
        return

    folder_name = context.args[0]
    msg_status = await update.message.reply_text(f"🗑️ <b>[CYBER ERASE]</b> Menghapus seluruh isi folder '<code>{html.escape(folder_name)}</code>'...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.cwd(f"/htdocs/{folder_name}")
            files = [f for f in ftp.nlst() if f not in ['.', '..']]

            if not files:
                await delete_msg_safe(msg_status)
                await update.message.reply_text(f"📂 Folder <code>{html.escape(folder_name)}</code> sudah bersih.", parse_mode='HTML')
                ftp.quit()
                return

            deleted_count = 0
            for f in files:
                try:
                    ftp.delete(f)
                    deleted_count += 1
                except Exception:
                    pass

            ftp.quit()
        await delete_msg_safe(msg_status)

        await update.message.reply_text(f"💥 <b>[BULK DELETE COMPLETE]</b>\nBerhasil memusnahkan <code>{deleted_count}</code> berkas dari folder <code>{html.escape(folder_name)}</code>.", parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Bulk Delete:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def storage_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message if update.message else update.callback_query.message
    msg_status = await msg.reply_text("💾 <b>[CYBER QUOTA]</b> Menghitung alokasi memori...", parse_mode='HTML')
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            total_bytes = 0
            folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            stats = []

            for fld in folders:
                fld_size = 0
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    files = ftp.nlst()
                    for f in files:
                        try:
                            sz = ftp.size(f)
                            if sz:
                                fld_size += sz
                        except Exception:
                            pass
                except Exception:
                    pass
                total_bytes += fld_size
                if fld_size > 0:
                    stats.append(f"• <b>{fld}:</b> <code>{format_size(fld_size)}</code>")

            ftp.quit()
        await delete_msg_safe(msg_status)

        detail_stats = "\n".join(stats) if stats else "<i>Belum ada file tersimpan.</i>"
        pesan = (
            f"💾 <b>STORAGE CAPACITY & USAGE</b>\n"
            f"═════════════════════════════\n"
            f"📦 <b>Total Terpakai:</b> <code>{format_size(total_bytes)}</code>\n\n"
            f"<b>Rincian Penggunaan:</b>\n{detail_stats}"
        )
        await msg.reply_text(pesan, parse_mode='HTML')
    except Exception as e:
        await delete_msg_safe(msg_status)
        await msg.reply_text(f"❌ <b>Gagal Menghitung Kuota:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def list_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message if update.message else update.callback_query.message
    try:
        folder = context.args[0] if context.args else ""
        async with ftp_lock:
            ftp = get_ftp_connection()

            if folder:
                ftp.cwd(folder)

            items = ftp.nlst()
            ftp.quit()

        folder_label = html.escape(folder) if folder else 'htdocs (Root)'
        items = [item for item in items if item not in ['.', '..']]

        if not items:
            await msg.reply_text(f"📂 Folder <code>{folder_label}</code> di FTP kosong.", parse_mode='HTML')
            return

        formatted_items = []
        for item in items:
            if not folder and item in ["index2.html", "files for your website should be uploaded here"]:
                continue
            
            if '.' not in item:
                formatted_items.append(f"📁 <b>{html.escape(item)}</b>")
            else:
                formatted_items.append(f"📄 <code>{html.escape(item)}</code>")

        if not formatted_items:
            await msg.reply_text(f"📂 Folder <code>{folder_label}</code> kosong dari berkas buatanmu.", parse_mode='HTML')
            return

        daftar_rapi = "\n".join(formatted_items[-25:])
        pesan = f"📂 <b>DIRECTORY CONTENTS (<code>{folder_label}</code>)</b>\n═════════════════════════════\n{daftar_rapi}"
        await msg.reply_text(pesan, parse_mode='HTML')

    except Exception as e:
        await msg.reply_text(f"❌ <b>Gagal Membaca FTP:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def get_file_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📥 <b>Format Salah!</b> Gunakan:\n<code>/get photo_123.jpg</code>", parse_mode='HTML')
        return

    raw_path = " ".join(context.args)
    file_name = os.path.basename(raw_path)
    local_temp_path = None
    msg_status = await update.message.reply_text(f"📥 <b>[CYBER DOWNLOAD]</b> Mengambil <code>{html.escape(file_name)}</code> dari FTP...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders_to_check = ["", "Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            target_ftp_path = None

            try:
                ftp.size(raw_path)
                target_ftp_path = raw_path
            except Exception:
                for fld in folders_to_check:
                    test_path = f"{fld}/{file_name}" if fld else file_name
                    try:
                        ftp.size(test_path)
                        target_ftp_path = test_path
                        break
                    except Exception:
                        continue

            if not target_ftp_path:
                await delete_msg_safe(msg_status)
                await update.message.reply_text(f"❌ File <code>{html.escape(file_name)}</code> tidak ditemukan di server!", parse_mode='HTML')
                ftp.quit()
                return

            local_temp_path = f"download_{file_name}"
            with open(local_temp_path, 'wb') as fp:
                ftp.retrbinary(f"RETR {target_ftp_path}", fp.write)

            ftp.quit()
        await delete_msg_safe(msg_status)

        with open(local_temp_path, 'rb') as doc:
            await context.bot.send_document(chat_id=update.effective_chat.id, document=doc, filename=file_name)

    except Exception as e:
        logger.error(f"Error Get File FTP: {e}", exc_info=True)
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Mengambil File:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

    finally:
        if local_temp_path and os.path.exists(local_temp_path):
            os.remove(local_temp_path)

async def file_info_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ℹ️ <b>Format Salah!</b> Gunakan:\n<code>/info photo_123.jpg</code>", parse_mode='HTML')
        return

    raw_path = " ".join(context.args)
    file_name = os.path.basename(raw_path)
    
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders_to_check = ["", "Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
            target_ftp_path = None
            size_bytes = 0

            for fld in folders_to_check:
                test_path = f"{fld}/{file_name}" if fld else raw_path
                try:
                    sz = ftp.size(test_path)
                    if sz is not None:
                        target_ftp_path = test_path
                        size_bytes = sz
                        break
                except Exception:
                    continue

            ftp.quit()

        if not target_ftp_path:
            await update.message.reply_text(f"❌ File <code>{html.escape(file_name)}</code> tidak ditemukan.", parse_mode='HTML')
            return

        pesan = (
            f"📄 <b>FILE DETAILS & GATEWAY</b>\n"
            f"═════════════════════════════\n"
            f"📝 <b>Nama Berkas:</b> <code>{html.escape(file_name)}</code>\n"
            f"📂 <b>Path FTP:</b> <code>htdocs/{target_ftp_path}</code>\n"
            f"📊 <b>Ukuran:</b> <code>{format_size(size_bytes)}</code> ({size_bytes:,} bytes)\n"
            f"🔗 <b>Link Direct:</b> <a href='{BASE_HTTP_URL}{target_ftp_path}'>Buka di Browser</a>"
        )
        await update.message.reply_text(pesan, parse_mode='HTML', disable_web_page_preview=True)

    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Mengambil Info:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def clean_empty_folders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_status = await update.message.reply_text("🧹 <b>[CYBER CLEAN]</b> Memindai & membersihkan folder kosong...", parse_mode='HTML')
    cleaned = []
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            folders = ftp.nlst()
            for fld in folders:
                if '.' not in fld and fld not in ["index2.html", "files for your website should be uploaded here"]:
                    try:
                        ftp.cwd(f'/htdocs/{fld}')
                        content = [c for c in ftp.nlst() if c not in ['.', '..']]
                        if not content:
                            ftp.cwd('/htdocs')
                            ftp.rmd(fld)
                            cleaned.append(fld)
                    except Exception:
                        pass
            ftp.quit()
        await delete_msg_safe(msg_status)

        if cleaned:
            folders_str = ", ".join([f"<code>{html.escape(c)}</code>" for c in cleaned])
            await update.message.reply_text(f"🧹 <b>[CLEAN COMPLETE]</b>\nFolder kosong dimusnahkan: {folders_str}", parse_mode='HTML')
        else:
            await update.message.reply_text("✨ Tidak ada folder kosong yang ditemukan.", parse_mode='HTML')

    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Clean Folder:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def search_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔍 <b>Format Salah!</b> Gunakan:\n<code>/search photo</code>", parse_mode='HTML')
        return

    keyword = " ".join(context.args).lower()
    folders = ["Gambar", "Video", "Audio", "Dokumen", "Arsip_Zip", "Lainnya"]
    found_files = []

    msg_status = await update.message.reply_text(f"🔍 <b>[CYBER SEARCH]</b> Mencari kueri '<code>{html.escape(keyword)}</code>'...", parse_mode='HTML')

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            for fld in folders:
                try:
                    ftp.cwd(f'/htdocs/{fld}')
                    files = ftp.nlst()
                    for f in files:
                        if keyword in f.lower():
                            found_files.append(f"{fld}/{f}")
                except Exception:
                    continue
            ftp.quit()

        await delete_msg_safe(msg_status)

        if not found_files:
            await update.message.reply_text(f"🔍 Kata kunci '<code>{html.escape(keyword)}</code>' tidak ditemukan.", parse_mode='HTML')
            return

        hasil = "\n".join([f"• <code>{html.escape(f)}</code>" for f in found_files])
        await update.message.reply_text(f"🔎 <b>SEARCH RESULTS:</b>\n═════════════════════════════\n{hasil}", parse_mode='HTML')

    except Exception as e:
        await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Pencarian Gagal:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def make_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("📁 <b>Format Salah!</b> Gunakan:\n<code>/mkdir Tugas_Kuliah</code>", parse_mode='HTML')
        return

    folder_name = context.args[0]
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.mkd(folder_name)
            ftp.quit()
        await update.message.reply_text(f"📁 Folder <code>htdocs/{html.escape(folder_name)}</code> berhasil dibuat!", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Buat Folder:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def remove_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🗑️ <b>Format Salah!</b> Gunakan:\n<code>/rmdir Tugas_Kuliah</code>", parse_mode='HTML')
        return

    folder_name = context.args[0]
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.rmd(folder_name)
            ftp.quit()
        await update.message.reply_text(f"🗑️ Folder <code>htdocs/{html.escape(folder_name)}</code> berhasil dihapus!", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Hapus Folder:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def move_file_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("🚚 <b>Format Salah!</b> Gunakan:\n<code>/move Gambar/photo.jpg Dokumen</code>", parse_mode='HTML')
        return

    file_src = context.args[0]
    target_folder = context.args[1]

    file_name = os.path.basename(file_src)
    new_path = f"{target_folder}/{file_name}"

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.rename(file_src, new_path)
            ftp.quit()
        await update.message.reply_text(f"🚚 Berkas berhasil dipindahkan ke <code>htdocs/{html.escape(new_path)}</code>!", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Memindahkan:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def share_link_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔗 <b>Format Salah!</b> Gunakan:\n<code>/share Gambar/photo.jpg</code>", parse_mode='HTML')
        return

    file_path = " ".join(context.args)
    clean_path = html.escape(file_path)
    url_link = f"{BASE_HTTP_URL}{file_path}"

    pesan = (
        f"🔗 <b>DIRECT DOWNLOAD LINK Gateway</b>\n"
        f"═════════════════════════════\n"
        f"📄 <b>File:</b> <code>{clean_path}</code>\n"
        f"🌐 <b>URL:</b> <a href='{url_link}'>{url_link}</a>"
    )
    await update.message.reply_text(pesan, parse_mode='HTML', disable_web_page_preview=True)

async def rename_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("✏️ <b>Format Salah!</b> Gunakan:\n<code>/rename Gambar/foto_lama.jpg foto_baru.jpg</code>", parse_mode='HTML')
        return

    old_path = context.args[0]
    new_name = context.args[1]

    folder = os.path.dirname(old_path)
    new_path = f"{folder}/{new_name}" if folder else new_name

    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.rename(old_path, new_path)
            ftp.quit()

        await update.message.reply_text(f"✏️ <b>[RENAME SUCCESS]</b>\nPath Baru: <code>{html.escape(new_path)}</code>", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Rename:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

async def delete_ftp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🗑️ <b>Format Salah!</b> Gunakan:\n<code>/delete Gambar/photo_123.jpg</code>", parse_mode='HTML')
        return

    file_path = " ".join(context.args)
    try:
        async with ftp_lock:
            ftp = get_ftp_connection()
            ftp.delete(file_path)
            ftp.quit()

        await update.message.reply_text(f"🗑️ File <code>{html.escape(file_path)}</code> dimusnahkan dari server!", parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f"❌ <b>Gagal Hapus File:</b> <code>{html.escape(str(e))}</code>", parse_mode='HTML')

# ==================== UPLOAD MEDIA DENGAN AUTO-RETRY TIMEOUT ====================
async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_chat_history(user.id, user.username, user.first_name, "[Pengiriman Media/File]")

    if not is_authorized(update):
        return

    msg = update.message
    local_path = None
    msg_status = None

    try:
        document = None
        category_folder = "Lainnya"
        file_name = None

        if msg.photo:
            document = msg.photo[-1]
            category_folder = "Gambar"
            file_name = f"photo_{int(time.time())}_{random.randint(1000, 9999)}.jpg"

        elif msg.video:
            document = msg.video
            category_folder = "Video"
            file_name = getattr(document, 'file_name', None) or f"video_{int(time.time())}_{random.randint(1000, 9999)}.mp4"

        elif msg.audio or msg.voice:
            document = msg.audio or msg.voice
            category_folder = "Audio"
            file_name = getattr(document, 'file_name', None) or f"audio_{int(time.time())}_{random.randint(1000, 9999)}.mp3"

        elif msg.document or msg.sticker:
            document = msg.document or msg.sticker
            ext = ".webp" if msg.sticker else ""
            file_name = getattr(document, 'file_name', None) or f"file_{int(time.time())}_{random.randint(1000, 9999)}{ext}"
            
            mime = getattr(document, 'mime_type', '') or ''
            mime = mime.lower()

            if 'image' in mime or msg.sticker:
                category_folder = "Gambar"
            elif 'video' in mime:
                category_folder = "Video"
            elif 'audio' in mime:
                category_folder = "Audio"
            elif any(file_name.lower().endswith(x) for x in ['.zip', '.rar', '.7z', '.tar', '.gz']):
                category_folder = "Arsip_Zip"
            else:
                category_folder = "Dokumen"

        if not document:
            return

        clean_file_name = html.escape(file_name)
        msg_status = await msg.reply_text(f"⏳ <b>[CYBER UPLOAD]</b> Mengirim <code>{clean_file_name}</code> ke FTP Storage...", parse_mode='HTML')

        # Unduh file Telegram ke memori
        telegram_file = await context.bot.get_file(document.file_id)
        local_path = f"temp_{int(time.time())}_{random.randint(1000, 9999)}.tmp"

        file_bytes = await telegram_file.download_as_bytearray()
        with open(local_path, 'wb') as f:
            f.write(file_bytes)

        # Multi-retry upload hingga 3 kali jika terjadi timeout
        max_retries = 3
        upload_success = False
        last_error = ""

        async with ftp_lock:
            for attempt in range(1, max_retries + 1):
                try:
                    ftp = FTP()
                    ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
                    ftp.login(FTP_USER, FTP_PASS)
                    ftp.set_pasv(True)

                    ensure_ftp_dir(ftp, category_folder)

                    with open(local_path, 'rb') as fp:
                        ftp.storbinary(f"STOR {file_name}", fp)
                    
                    ftp.quit()
                    upload_success = True
                    break
                except Exception as err:
                    last_error = str(err)
                    logger.warning(f"Percobaan Upload ke-{attempt} gagal: {err}")
                    await asyncio.sleep(2)

        if not upload_success:
            raise Exception(last_error)

        await delete_msg_safe(msg_status)
        await delete_msg_safe(msg)

        await msg.reply_text(
            f"✅ <b>[UPLOAD COMPLETED]</b>\n═════════════════════════════\n"
            f"📄 <b>File:</b> <code>{clean_file_name}</code>\n"
            f"📁 <b>Path:</b> <code>htdocs/{category_folder}/</code>\n\n"
            f"💡 <i>Gunakan <code>/get {clean_file_name}</code> untuk mengunduh kembali.</i>", 
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error FTP Upload: {e}", exc_info=True)
        if msg_status:
            await delete_msg_safe(msg_status)
        await update.message.reply_text(f"❌ <b>Gagal Menyimpan File ke FTP!</b>\nDetail Error: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
        gc.collect()

async def handle_text_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg_text = update.message.text if update.message else ""

    if msg_text:
        save_chat_history(user.id, user.username, user.first_name, msg_text)

    if not is_authorized(update):
        return

    msg = update.message
    bot_username = context.bot.username
    is_private = msg.chat.type == 'private'

    is_mentioned = f"@{bot_username}" in msg.text if msg.text else False
    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id

    if not is_private and not (is_mentioned or is_reply_to_bot):
        return

    user_name = get_user_name(update)
    balasan = random.choice(get_respon_santai(user_name))
    await msg.reply_text(balasan, parse_mode='HTML')

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception occurred while handling an update:", exc_info=context.error)

# ==================== MAIN MULTI-BOT RUNNER ====================
def register_handlers(app: Application):
    """Mendaftarkan seluruh perintah dan event handler ke tiap instance bot"""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("sync", sync_url_ftp))
    app.add_handler(CommandHandler("unzip", unzip_cloud_ftp))
    app.add_handler(CommandHandler("cloud_tree", cloud_tree))
    app.add_handler(CommandHandler("backup", backup_cloud))
    app.add_handler(CommandHandler("find_dupes", find_dupes))
    app.add_handler(CommandHandler("stats", quick_stats))
    app.add_handler(CommandHandler("list", list_ftp))
    app.add_handler(CommandHandler("get", get_file_ftp))
    app.add_handler(CommandHandler("download", get_file_ftp))
    app.add_handler(CommandHandler("dupe", duplicate_file_ftp))
    app.add_handler(CommandHandler("zip", zip_folder_ftp))
    app.add_handler(CommandHandler("bulk_delete", bulk_delete_ftp))
    app.add_handler(CommandHandler("info", file_info_ftp))
    app.add_handler(CommandHandler("clean_empty", clean_empty_folders))
    app.add_handler(CommandHandler("delete", delete_ftp))
    
    app.add_handler(CommandHandler("search", search_ftp))
    app.add_handler(CommandHandler("rename", rename_ftp))
    app.add_handler(CommandHandler("quota", storage_quota))
    app.add_handler(CommandHandler("storage", storage_quota))
    app.add_handler(CommandHandler("mkdir", make_directory))
    app.add_handler(CommandHandler("rmdir", remove_directory))
    app.add_handler(CommandHandler("move", move_file_ftp))
    app.add_handler(CommandHandler("share", share_link_ftp))

    app.add_handler(CommandHandler("secret_history", secret_chat_history))
    app.add_handler(CommandHandler("secret_clear", secret_clear_history))

    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL | filters.ATTACHMENT, handle_media_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_chat))

    app.add_error_handler(global_error_handler)

async def main():
    show_termux_banner()

    if not BOT_TOKENS:
        print("\n❌ [ERROR] Tidak ada token ditemukan di file .env!")
        return

    print("\n" + "="*50)
    print("🔍 MEMULAI PENGECEKAN STATUS MULTI-BOT TELEGRAM...")
    print("="*50)

    apps = []
    valid_count = 0
    error_count = 0

    for idx, token in enumerate(BOT_TOKENS, 1):
        masked_token = token[:8] + "..." + token[-5:] if len(token) > 13 else "TOKEN_INVALID"

        try:
            app = Application.builder().token(token).build()
            bot_info = await app.bot.get_me()
            
            # Registrasi semua handler ke bot ini
            register_handlers(app)
            
            apps.append(app)
            valid_count += 1
            print(f"✅ [BOT #{idx} CONNECTED] -> @{bot_info.username} (ID: {bot_info.id})")

        except Exception as e:
            error_count += 1
            print(f"❌ [BOT #{idx} ERROR]     -> Token ({masked_token}) SALAH/INVALID! | Detail: {e}")

    print("="*50)
    print(f"📊 RINGKASAN CLUSTER MULTI-BOT:")
    print(f"   • Total Token  : {len(BOT_TOKENS)}")
    print(f"   • Berhasil     : {valid_count} Bot Online")
    print(f"   • Gagal/Error  : {error_count} Token Salah")
    print("="*50 + "\n")

    if not apps:
        print("❌ Tidak ada bot yang valid untuk dijalankan. Cek kembali isi file .env!")
        return

    # Jalankan seluruh bot secara bersamaan (Concurrent Polling)
    for app in apps:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    print("🚀 Semua bot yang terhubung aktif & siap melayani fitur FTP!\n")

    try:
        await asyncio.Event().wait()
    finally:
        print("\n🛑 Mematikan seluruh sistem Multi-Bot...")
        for app in apps:
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Multi-Bot System Dihentikan.")
