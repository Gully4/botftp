import os
import logging
import traceback
from ftplib import FTP
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from google import genai

# ================= KONFIGURASI LOGGING =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= KONFIGURASI KREDENSIAL =================
TELEGRAM_TOKEN = "8924766752:AAHWnJ6fNIbpXkg8EfNhRoQmFI0SarJ1mBA"
GEMINI_API_KEY = "AQ.Ab8RN6J87_HqCt-_KKymQNVjUyQHdY-tgxqsg4_ITLANxMLA_Q"

FTP_HOST = "ftpupload.net"      # IP/Host Server FTP kamu
FTP_USER = "if0_43064672"
FTP_PASS = "ki2fICWM6nN7m"
FTP_PORT = 21                       # Port bawaan FTP (biasanya 21)
# =========================================================

# Inisialisasi Client Gemini AI
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    logger.error(f"Gagal inisialisasi Gemini AI: {e}")
    ai_client = None

def ensure_ftp_dir(ftp, folder_name):
    try:
        ftp.cwd(folder_name)
    except Exception:
        ftp.mkd(folder_name)
        ftp.cwd(folder_name)

def start(update, context):
    pesan = (
        "Yo bro! Gue siap bertugas 24/7 di Chat Pribadi maupun Grup/Channel! 🤖🔥\n\n"
        "📌 **Fitur:**\n"
        "• **Upload File**: Kirim file apa saja (Foto, Video, Musik, PDF, Zip) di grup/chat pribadi.\n"
        "• **Ngobrol/Tanya AI**: Tag/Mention gue (`@username_bot`) atau balaskan pesan ke pesan gue!"
    )
    update.message.reply_text(pesan, parse_mode='Markdown')

# --- FITUR 1: MANAJEMEN UPLOAD & PENGELOMPOKAN FILE KE FTP ---
def handle_docs(update, context):
    local_path = None
    try:
        msg = update.message
        document = msg.document or msg.audio or msg.video or msg.voice
        category_folder = "Lainnya"

        if msg.photo:
            document = msg.photo[-1]
            category_folder = "Gambar"
            file_name = f"photo_{document.file_id}.jpg"
        elif msg.video:
            category_folder = "Video"
            file_name = getattr(document, 'file_name', f"video_{document.file_id}.mp4")
        elif msg.audio or msg.voice:
            category_folder = "Audio"
            file_name = getattr(document, 'file_name', f"audio_{document.file_id}.mp3")
        elif msg.document:
            mime = getattr(document, 'mime_type', '').lower()
            original_name = getattr(document, 'file_name', 'file_tanpa_nama')
            file_name = original_name

            if 'image' in mime:
                category_folder = "Gambar"
            elif 'video' in mime:
                category_folder = "Video"
            elif 'audio' in mime:
                category_folder = "Audio"
            elif any(ext in original_name.lower() for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.ppt']):
                category_folder = "Dokumen"
            elif any(ext in original_name.lower() for ext in ['.zip', '.rar', '.7z', '.tar', '.gz']):
                category_folder = "Arsip_Zip"
            else:
                category_folder = "Dokumen"

        if not document:
            return

        msg.reply_text(f"⏳ File '{file_name}' dideteksi jenis **{category_folder}**. Mengunduh...", parse_mode='Markdown')

        telegram_file = context.bot.get_file(document.file_id)
        local_path = f"/tmp/{file_name}"
        telegram_file.download(local_path)

        msg.reply_text(f"🚀 Mengunggah ke FTP di folder `/FTP/{category_folder}/`...")

        ftp = FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)

        ensure_ftp_dir(ftp, category_folder)

        with open(local_path, 'rb') as fp:
            ftp.storbinary(f"STOR {file_name}", fp)
        
        ftp.quit()

        msg.reply_text(f"✅ BERHASIL! File '{file_name}' telah rapi tersimpan di folder **{category_folder}**!")

    except Exception as e:
        logger.error(f"Error saat upload file: {e}", exc_info=True)
        update.message.reply_text(f"❌ Gagal mengunggah file. Error Detail:\n`{str(e)}`", parse_mode='Markdown')

    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
            logger.info(f"File sementara {local_path} berhasil dibersihkan.")

# --- FITUR 2: RESPON CHAT CERDAS DI GRUP DAN CHAT PRIBADI ---
def handle_ai_chat(update, context):
    msg = update.message
    bot_username = context.bot.username
    is_private = msg.chat.type == 'private'

    is_mentioned = f"@{bot_username}" in msg.text if msg.text else False
    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id

    if not is_private and not (is_mentioned or is_reply_to_bot):
        return

    user_text = msg.text.replace(f"@{bot_username}", "").strip()
    if not user_text:
        msg.reply_text("Ya bro, ada yang bisa gue bantu?")
        return

    context.bot.send_chat_action(chat_id=msg.chat_id, action="typing")

    try:
        if not ai_client:
            msg.reply_text("❌ Kunci API Gemini belum dikonfigurasi dengan benar.")
            return

        system_instruction = (
            "Kamu adalah bot asisten Telegram yang santai, ramah, dan solutif. "
            "Kamu aktif di chat pribadi maupun grup. Panggil pengguna dengan sebutan 'bro'. "
            "Gunakan bahasa Indonesia kasual yang menyenangkan dan jelas."
        )

        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{system_instruction}\n\nPesan dari user: {user_text}"
        )
        
        msg.reply_text(response.text)

    except Exception as e:
        logger.error(f"Error pada AI Chat: {e}", exc_info=True)
        msg.reply_text(f"Waduh bro, AI-nya lagi pusing/error nih.\nDetail: `{str(e)}`", parse_mode='Markdown')

# --- SISTEM PENDETEKSI ERROR TERPUSAT (GLOBAL ERROR HANDLER) ---
def global_error_handler(update, context):
    logger.error(msg="Exception occurred while handling an update:", exc_info=context.error)
    
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    error_message = f"🚨 **SISTEM MENGALAMI ERROR!**\n\n```python\n{tb_string[-500:]}\n```"

    if update and update.effective_message:
        try:
            update.effective_message.reply_text(error_message, parse_mode='Markdown')
        except Exception:
            update.effective_message.reply_text(f"🚨 Terjadi Error Sistem: {context.error}")

def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    
    # Handlers File & Chat
    dp.add_handler(MessageHandler(Filters.document | Filters.photo | Filters.audio | Filters.video | Filters.voice, handle_docs))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_ai_chat))

    # REGISTER ERROR HANDLER GLOBAL
    dp.add_error_handler(global_error_handler)

    logger.info("Bot berhasil berjalan...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
