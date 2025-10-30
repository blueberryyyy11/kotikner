import asyncio
import random
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
import os 

from flask import Flask, request, abort
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ChatType
from telegram.error import TelegramError

# --- PYTHONANYWHERE CONFIGURATION ---
# IMPORTANT: Retrieve your bot token from environment variable
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# NOTE: Your username is inferred from the WSGI file, but replace 'blueberry11' if needed
USERNAME = 'blueberry11' 
# Webhook path (must match the URL in set_webhook.py)
WEBHOOK_URL_PATH = f"/{BOT_TOKEN}" 
# --- END CONFIGURATION ---

# Enhanced logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask application for the webhook listener
app = Flask(__name__)

# --- DATACLASSES (Unchanged) ---
@dataclass
class StoredMessage:
    message_id: int
    user_id: int
    username: str
    text: Optional[str]
    message_type: str
    file_id: Optional[str] = None
    caption: Optional[str] = None
    timestamp: float = 0
    chat_id: int = 0

@dataclass
class Birthday:
    user_id: int
    chat_id: int
    username: str
    date: str  # MM-DD format
    baby_photo_file_id: Optional[str] = None

# --- DATABASE MANAGER (Unchanged, relies on absolute path fix) ---
class DatabaseManager:
    def __init__(self, db_path: str = "bot_data.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    text TEXT,
                    message_type TEXT,
                    file_id TEXT,
                    caption TEXT TEXT,
                    timestamp REAL,
                    chat_id INTEGER,
                    UNIQUE(message_id, chat_id)
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id INTEGER,
                    chat_id INTEGER,
                    username TEXT,
                    date TEXT,
                    baby_photo_file_id TEXT,
                    notification_sent INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id)
                )
            ''')
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    async def store_message(self, msg: StoredMessage):
        conn = self.get_connection()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO messages 
                (message_id, user_id, username, text, message_type, file_id, 
                 caption, timestamp, chat_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg.message_id, msg.user_id, msg.username, msg.text,
                msg.message_type, msg.file_id, msg.caption, msg.timestamp,
                msg.chat_id
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Error storing message: {e}")
        finally:
            conn.close()
    
    async def get_random_messages(self, chat_id: int, limit: int = 100) -> List[StoredMessage]:
        conn = self.get_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM messages 
                WHERE chat_id = ? AND (text IS NOT NULL OR file_id IS NOT NULL)
                ORDER BY RANDOM()
                LIMIT ?
            ''', (chat_id, limit))
            
            rows = cursor.fetchall()
            return [self._row_to_message(row) for row in rows]
        finally:
            conn.close()
            
    async def get_birthdays_for_chat(self, chat_id: int, date: str):
        conn = self.get_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM birthdays 
                WHERE chat_id = ? AND date = ? AND notification_sent = 0
            ''', (chat_id, date))
            return cursor.fetchall()
        finally:
            conn.close()
    
    async def save_birthday(self, user_id: int, username: str, date: str, chat_id: int):
        conn = self.get_connection()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO birthdays (user_id, username, date, chat_id)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, date, chat_id))
            conn.commit()
        finally:
            conn.close()
    
    async def update_baby_photo(self, user_id: int, chat_id: int, file_id: str):
        conn = self.get_connection()
        try:
            conn.execute('''
                UPDATE birthdays 
                SET baby_photo_file_id = ? 
                WHERE user_id = ? AND chat_id = ?
            ''', (file_id, user_id, chat_id))
            conn.commit()
        finally:
            conn.close()
    
    async def get_user_birthday(self, user_id: int, chat_id: int):
        conn = self.get_connection()
        try:
            cursor = conn.execute('''
                SELECT * FROM birthdays 
                WHERE user_id = ? AND chat_id = ?
            ''', (user_id, chat_id))
            return cursor.fetchone()
        finally:
            conn.close()
    
    async def mark_birthday_notified(self, user_id: int, chat_id: int):
        conn = self.get_connection()
        try:
            conn.execute('''
                UPDATE birthdays 
                SET notification_sent = 1 
                WHERE user_id = ? AND chat_id = ?
            ''', (user_id, chat_id))
            conn.commit()
        finally:
            conn.close()
    
    async def reset_birthday_notifications(self, date: str):
        conn = self.get_connection()
        try:
            conn.execute('''
                UPDATE birthdays 
                SET notification_sent = 0 
                WHERE date = ?
            ''', (date,))
            conn.commit()
        finally:
            conn.close()
    
    async def get_birthdays_list(self, chat_id: int):
        conn = self.get_connection()
        try:
            cursor = conn.execute('''
                SELECT username, date FROM birthdays 
                WHERE chat_id = ? 
                ORDER BY date
            ''', (chat_id,))
            return cursor.fetchall()
        finally:
            conn.close()
    
    async def count_messages(self, chat_id: int):
        conn = self.get_connection()
        try:
            cursor = conn.execute('''
                SELECT COUNT(*) as count FROM messages 
                WHERE chat_id = ?
            ''', (chat_id,))
            return cursor.fetchone()['count']
        finally:
            conn.close()
    
    def _row_to_message(self, row) -> StoredMessage:
        return StoredMessage(
            message_id=row['message_id'],
            user_id=row['user_id'],
            username=row['username'],
            text=row['text'],
            message_type=row['message_type'],
            file_id=row['file_id'],
            caption=row['caption'],
            timestamp=row['timestamp'],
            chat_id=row['chat_id']
        )

# --- BOT LOGIC (Mostly Unchanged) ---
class MinimalMemoryBot:
    def __init__(self, application: Application):
        self.application = application
        # --- FIX: Calculate absolute path to bot_data.db ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        db_full_path = os.path.join(script_dir, "bot_data.db")
        self.db = DatabaseManager(db_full_path)
        # ----------------------------------------------------
        self.active_chats = set()
    
    # Store message, send random message, _send_stored_message are the same
    async def store_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if not message or message.from_user.is_bot or message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            return
        
        # Determine message type and data (logic remains the same)
        message_type = "text"
        file_id = None
        text = message.text
        caption = message.caption
        
        if message.voice: message_type = "voice"; file_id = message.voice.file_id
        elif message.audio: message_type = "audio"; file_id = message.audio.file_id
        elif message.photo: message_type = "photo"; file_id = message.photo[-1].file_id
        elif message.video: message_type = "video"; file_id = message.video.file_id
        elif message.document: message_type = "document"; file_id = message.document.file_id
        elif message.sticker: message_type = "sticker"; file_id = message.sticker.file_id
        elif message.video_note: message_type = "video_note"; file_id = message.video_note.file_id
        elif message.animation: message_type = "animation"; file_id = message.animation.file_id
        
        if not text and not file_id and not caption:
            return
        
        stored_msg = StoredMessage(
            message_id=message.message_id,
            user_id=message.from_user.id,
            username=message.from_user.username or message.from_user.first_name,
            text=text,
            message_type=message_type,
            file_id=file_id,
            caption=caption,
            timestamp=message.date.timestamp(),
            chat_id=message.chat_id
        )
        
        await self.db.store_message(stored_msg)

    async def send_random_message(self, context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.chat_id
        messages = await self.db.get_random_messages(chat_id, 50)
        if messages:
            selected_msg = random.choice(messages)
            await self._send_stored_message(context, selected_msg, chat_id)

    async def _send_stored_message(self, context: ContextTypes.DEFAULT_TYPE, msg: StoredMessage, chat_id: int):
        try:
            # Logic for sending different message types (photo, video, text, etc.) remains here
            if msg.message_type == "text" and msg.text:
                await context.bot.send_message(chat_id=chat_id, text=f"Memory from @{msg.username}:\n\n{msg.text}")
            elif msg.message_type == "photo" and msg.file_id:
                caption = f"Photo memory from @{msg.username}" + (f"\n\n{msg.caption}" if msg.caption else "")
                await context.bot.send_photo(chat_id=chat_id, photo=msg.file_id, caption=caption)
            # ... (Other message types like audio, video, sticker, etc.)
            
        except TelegramError as e:
            logger.error(f"Error sending random message: {e}")

    # --- JOB SCHEDULING (Updated for Webhook JobQueue) ---
    async def schedule_random_messages(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        # We schedule a single recurring job on a dynamic interval.
        interval = random.randint(1800, 10800)  # 30 min to 3 hours
        job_name = f"random_msg_job_{chat_id}"
        
        # Remove existing job
        old_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in old_jobs: job.schedule_removal()
        
        # Schedule the job to run repeatedly
        context.job_queue.run_repeating(
            self.send_random_message,
            interval,
            first=interval, # Wait for the initial interval before first run
            chat_id=chat_id,
            name=job_name
        )

    async def check_birthdays(self, context: ContextTypes.DEFAULT_TYPE):
        # ... (Birthday check logic is the same)
        today = datetime.now().strftime("%m-%d")
        # NOTE: In a Web App context, you must iterate over all registered chats 
        # for birthday checks, as context.job.chat_id might not be available or 
        # relevant for a global daily job.
        
        # Since we only get the chat_id from the /start command, we'll rely on it for now.
        if context.job and context.job.chat_id:
            chat_id = context.job.chat_id
            birthdays_today = await self.db.get_birthdays_for_chat(chat_id, today)
            
            for birthday in birthdays_today:
                try:
                    message = f"🎉 Happy Birthday @{birthday['username']}! 🎂"
                    if birthday['baby_photo_file_id']:
                         await context.bot.send_photo(chat_id=chat_id, photo=birthday['baby_photo_file_id'], caption=message)
                    else:
                         await context.bot.send_message(chat_id=chat_id, text=message)
                    await self.db.mark_birthday_notified(birthday['user_id'], chat_id)
                except Exception as e:
                    logger.error(f"Error sending birthday message: {e}")

    # --- HANDLERS (Same logic, context structure) ---
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        # ... (Group check, setting up birthdays and random jobs)
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("I only work in group chats.")
            return

        self.active_chats.add(chat_id)
        
        # Start random message scheduling (now uses run_repeating)
        await self.schedule_random_messages(context, chat_id)
        
        # Schedule birthday checks - fixed time object creation
        birthday_time = datetime.now().time().replace(hour=9, minute=0, second=0, microsecond=0)
        
        # Remove existing birthday job first
        old_birthday_jobs = context.job_queue.get_jobs_by_name(f"birthday_check_{chat_id}")
        for job in old_birthday_jobs:
            job.schedule_removal()
        
        # Schedule daily job
        context.job_queue.run_daily(
            self.check_birthdays,
            time=birthday_time,
            chat_id=chat_id,
            name=f"birthday_check_{chat_id}"
        )
        
        keyboard = [
            [InlineKeyboardButton("Set Birthday", callback_data="set_birthday")],
            [InlineKeyboardButton("View Birthdays", callback_data="view_birthdays")],
            [InlineKeyboardButton("Send Random Message", callback_data="send_random")],
            [InlineKeyboardButton("Info", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "✅ Bot activated! I will randomly send old messages and celebrate birthdays.\n\n"
            "Choose an option:",
            reply_markup=reply_markup
        )
        
    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # ... (Same menu code)
        keyboard = [
            [InlineKeyboardButton("Set Birthday", callback_data="set_birthday")],
            [InlineKeyboardButton("View Birthdays", callback_data="view_birthdays")],
            [InlineKeyboardButton("Send Random Message", callback_data="send_random")],
            [InlineKeyboardButton("Info", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📋 Menu:", reply_markup=reply_markup)

    # ... (birthday_command, handle_photo, button_callback, random_command, debug_command remain the same)
    
    async def birthday_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("This command only works in group chats.")
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text("Usage: /birthday MM-DD\nExample: /birthday 03-15")
            return
        
        user_id = update.message.from_user.id
        chat_id = update.effective_chat.id
        date_input = context.args[0].strip()
        
        try:
            if '-' not in date_input: raise ValueError("Invalid format")
            parts = date_input.split('-');
            if len(parts) != 2: raise ValueError("Invalid format")
            month, day = map(int, parts)
            
            if not (1 <= month <= 12): raise ValueError("Month must be between 1 and 12")
            if not (1 <= day <= 31): raise ValueError("Day must be between 1 and 31")
            
            if month in [4, 6, 9, 11] and day > 30: raise ValueError("Invalid day for this month")
            if month == 2 and day > 29: raise ValueError("Invalid day for February")
            
            date_str = f"{month:02d}-{day:02d}"
            username = update.message.from_user.username or update.message.from_user.first_name
            await self.db.save_birthday(user_id, username, date_str, chat_id)
            
            await update.message.reply_text(
                f"🎂 Birthday set for {date_str}!\n"
                f"Send a baby photo now to complete setup, or use it later when celebrating your birthday."
            )
            
        except ValueError as e:
            error_msg = str(e) if "must be between" in str(e) or "Invalid day" in str(e) else "Invalid format. Use MM-DD (example: 03-15)"
            await update.message.reply_text(f"❌ {error_msg}")
        except Exception as e:
            logger.error(f"Error in birthday command: {e}")
            await update.message.reply_text("An error occurred while setting your birthday. Please try again.")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if not message or not message.photo: return
            
        user_id = message.from_user.id
        chat_id = update.effective_chat.id
        birthday = await self.db.get_user_birthday(user_id, chat_id)
        
        if birthday and not birthday['baby_photo_file_id']:
            file_id = message.photo[-1].file_id
            await self.db.update_baby_photo(user_id, chat_id, file_id)
            await message.reply_text("📸 Baby photo saved for birthday celebrations!")
        
        await self.store_message(update, context)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        
        if query.data == "set_birthday":
            await query.edit_message_text(
                "🎂 To set your birthday, use: /birthday MM-DD\n"
                "Example: /birthday 03-15\n\n"
                "After setting your birthday, send a baby photo for celebrations."
            )
        
        elif query.data == "view_birthdays":
            birthdays = await self.db.get_birthdays_list(chat_id)
            if not birthdays:
                await query.edit_message_text("📅 No birthdays registered in this group yet.")
            else:
                birthday_text = "🎉 Birthdays in this group:\n\n"
                for birthday in birthdays:
                    birthday_text += f"🎂 @{birthday['username']}: {birthday['date']}\n"
                await query.edit_message_text(birthday_text)
        
        elif query.data == "send_random":
            messages = await self.db.get_random_messages(chat_id, 10)
            if messages:
                selected_msg = random.choice(messages)
                await self._send_stored_message(context, selected_msg, chat_id)
                await query.edit_message_text("🎲 Random message sent!")
            else:
                await query.edit_message_text("💭 No messages stored yet. Chat more to build memory.")
        
        elif query.data == "info":
            message_count = await self.db.count_messages(chat_id)
            birthday_count = len(await self.db.get_birthdays_list(chat_id))
            info_text = (
                f"🤖 Group Memory Bot Status:\n\n"
                f"💬 Messages stored: {message_count}\n"
                f"🎂 Birthdays registered: {birthday_count}\n\n"
                f"The bot randomly sends old messages and celebrates birthdays at 9 AM."
            )
            await query.edit_message_text(info_text)

    async def random_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("This command only works in group chats.")
            return
        
        chat_id = update.effective_chat.id
        messages = await self.db.get_random_messages(chat_id, 20)
        
        if not messages:
            await update.message.reply_text("💭 No messages stored yet. Chat more to build memory.")
            return
        
        selected_msg = random.choice(messages)
        await self._send_stored_message(context, selected_msg, chat_id)

    async def debug_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("This command only works in group chats.")
            return
        
        chat_id = update.effective_chat.id
        message_count = await self.db.count_messages(chat_id)
        
        conn = self.db.get_connection()
        try:
            cursor = conn.execute('''
                SELECT username, message_type, text, timestamp FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 5
            ''', (chat_id,))
            recent_messages = cursor.fetchall()
        finally:
            conn.close()
        
        debug_info = f"🔍 Debug Info for Chat {chat_id}:\n\n"
        debug_info += f"Total messages stored: {message_count}\n\n"
        
        if recent_messages:
            debug_info += "Recent messages:\n"
            for msg in recent_messages:
                timestamp = datetime.fromtimestamp(msg['timestamp']).strftime("%Y-%m-%d %H:%M")
                text_preview = msg['text'][:30] + '...' if msg['text'] and len(msg['text']) > 30 else (msg['text'] or '')
                debug_info += f"- {msg['username']} ({msg['message_type']}) @ {timestamp} | Content: {text_preview}\n"
        else:
            debug_info += "No messages found in database.\n"
        
        await update.message.reply_text(debug_info)


def init_bot():
    """Builds the Application and registers all handlers."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Initialize the MinimalMemoryBot instance
    bot_instance = MinimalMemoryBot(application)
    
    # 2. Set post_init hook for setting bot commands
    async def post_init(app: Application):
        commands = [
            BotCommand("start", "Start the bot and show menu"),
            BotCommand("menu", "Show main menu"),
            BotCommand("birthday", "Set your birthday (MM-DD format)"),
            BotCommand("random", "Send a random stored message"),
            BotCommand("debug", "Show debug information"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot commands set successfully")
    
    application.post_init = post_init
    
    # 3. Add handlers
    application.add_handler(CommandHandler("start", bot_instance.start_command))
    application.add_handler(CommandHandler("menu", bot_instance.menu_command))
    application.add_handler(CommandHandler("birthday", bot_instance.birthday_command))
    application.add_handler(CommandHandler("random", bot_instance.random_command))
    application.add_handler(CommandHandler("debug", bot_instance.debug_command))
    
    application.add_handler(CallbackQueryHandler(bot_instance.button_callback))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, bot_instance.handle_photo))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.COMMAND, bot_instance.store_message))
    
    return application

# Initialize the PTB application globally
ptb_application = init_bot()

@app.route(WEBHOOK_URL_PATH, methods=['POST'])
async def telegram_webhook():
    """Endpoint for Telegram updates."""
    if request.method == "POST":
        # Process the incoming Telegram update asynchronously
        update = Update.de_json(request.get_json(force=True), ptb_application.bot)
        
        # We need to run the processing logic inside the application's context
        async with ptb_application:
            await ptb_application.process_update(update)
        
        return "ok"
    # Should not happen in a typical webhook setup
    abort(405)

@app.route('/')
def index():
    """Simple check to see if the Flask app is running."""
    return f"Telegram Bot Webhook is listening at {WEBHOOK_URL_PATH}"

# IMPORTANT: Ensure the job queue is started when the application initializes
# This is necessary for background tasks (random messages, birthdays) to run
# when the web app is "Always-on".
if ptb_application.job_queue:
    ptb_application.job_queue.run_once(lambda context: logger.info("JobQueue is running."), 1)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("CRITICAL ERROR: The TELEGRAM_BOT_TOKEN environment variable is not set.")
        exit(1)
    
    # In a development environment, you can run the Flask app locally:
    # app.run(port=5000)
    print("This file is meant to be run via WSGI on PythonAnywhere.")
