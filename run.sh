
#!/bin/bash
pkg update && pkg upgrade -y
pkg install nodejs-lts -y
npm install -g pm2
pip install --upgrade --force-reinstall pytz apscheduler tzlocal
pm2 kill
pkill -f python
pip install python-dotenv python-telegram-bot
reset
pm2 start bot.py --name "bot"
pm2 status
pm2 start bot.py --interpreter python
reset
while true; do
    echo "[LOG] Menjalankan Bot Cloud Storage FTP..."
    python bot.py
    echo "[WARNING] Bot terhenti/crash! Restart otomatis dalam 3 detik..."
    sleep 3
done
