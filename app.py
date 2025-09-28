import asyncio
import random
import sqlite3
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)
from telegram.constants import ChatType
from telegram.error import TelegramError

# Enhanced logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                    caption TEXT,
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
            # Debug logging
            logger.info(f"Storing message: ID={msg.message_id}, User={msg.username}, Type={msg.message_type}, Chat={msg.chat_id}")
            
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
            logger.info(f"Message stored successfully: {msg.message_id}")
            
        except sqlite3.IntegrityError as e:
            logger.warning(f"Message already exists: {msg.message_id} - {e}")
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
            logger.info(f"Found {len(rows)} messages for chat {chat_id}")
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

class MinimalMemoryBot:
    def __init__(self, token: str):
        self.token = token
        self.db = DatabaseManager()
        self.active_chats = set()
        
    async def store_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        if not message or message.from_user.is_bot:
            logger.info("Skipping bot message or empty message")
            return
        
        # Only store messages from groups
        if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            logger.info("Skipping non-group message")
            return
        
        # Determine message type and data
        message_type = "text"
        file_id = None
        text = message.text
        caption = message.caption
        
        if message.voice:
            message_type = "voice"
            file_id = message.voice.file_id
        elif message.audio:
            message_type = "audio"
            file_id = message.audio.file_id
        elif message.photo:
            message_type = "photo"
            file_id = message.photo[-1].file_id
        elif message.video:
            message_type = "video"
            file_id = message.video.file_id
        elif message.document:
            message_type = "document"
            file_id = message.document.file_id
        elif message.sticker:
            message_type = "sticker"
            file_id = message.sticker.file_id
        elif message.video_note:
            message_type = "video_note"
            file_id = message.video_note.file_id
        elif message.animation:
            message_type = "animation"
            file_id = message.animation.file_id
        
        # Skip messages without content
        if not text and not file_id and not caption:
            logger.info("Skipping message without content")
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
        if not messages:
            logger.info(f"No messages found for chat {chat_id}")
            return
        
        selected_msg = random.choice(messages)
        await self._send_stored_message(context, selected_msg, chat_id)

    async def _send_stored_message(self, context: ContextTypes.DEFAULT_TYPE, msg: StoredMessage, chat_id: int):
        try:
            if msg.message_type == "text" and msg.text:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Memory from @{msg.username}:\n\n{msg.text}"
                )
                
            elif msg.message_type == "voice" and msg.file_id:
                await context.bot.send_voice(
                    chat_id=chat_id,
                    voice=msg.file_id,
                    caption=f"Voice memory from @{msg.username}"
                )
                
            elif msg.message_type == "photo" and msg.file_id:
                caption = f"Photo memory from @{msg.username}"
                if msg.caption:
                    caption += f"\n\n{msg.caption}"
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=msg.file_id,
                    caption=caption
                )
                
            elif msg.message_type == "video" and msg.file_id:
                caption = f"Video memory from @{msg.username}"
                if msg.caption:
                    caption += f"\n\n{msg.caption}"
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=msg.file_id,
                    caption=caption
                )
                
            elif msg.message_type == "audio" and msg.file_id:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=msg.file_id,
                    caption=f"Audio memory from @{msg.username}"
                )
                
            elif msg.message_type == "sticker" and msg.file_id:
                await context.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=msg.file_id
                )
                
            elif msg.message_type == "animation" and msg.file_id:
                caption = f"GIF memory from @{msg.username}"
                if msg.caption:
                    caption += f"\n\n{msg.caption}"
                await context.bot.send_animation(
                    chat_id=chat_id,
                    animation=msg.file_id,
                    caption=caption
                )
                
        except TelegramError as e:
            logger.error(f"Error sending random message: {e}")

    async def schedule_random_messages(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        # Random interval between 30 minutes and 3 hours
        interval = random.randint(1800, 10800)  # 30 min to 3 hours in seconds
        
        job_name = f"random_msg_{chat_id}"
        
        # Remove existing job
        old_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in old_jobs:
            job.schedule_removal()
        
        # Schedule new job
        context.job_queue.run_once(
            self.random_message_job,
            interval,
            chat_id=chat_id,
            name=job_name
        )

    async def random_message_job(self, context: ContextTypes.DEFAULT_TYPE):
        await self.send_random_message(context)
        # Schedule next message
        chat_id = context.job.chat_id
        await self.schedule_random_messages(context, chat_id)

    async def check_birthdays(self, context: ContextTypes.DEFAULT_TYPE):
        """Check for birthdays today and send celebratory messages"""
        today = datetime.now().strftime("%m-%d")
        chat_id = context.job.chat_id
        
        birthdays_today = await self.db.get_birthdays_for_chat(chat_id, today)
        
        for birthday in birthdays_today:
            try:
                message = f"🎉 Happy Birthday @{birthday['username']}! 🎂"
                
                if birthday['baby_photo_file_id']:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=birthday['baby_photo_file_id'],
                        caption=message
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                
                # Mark as notified for this specific chat
                await self.db.mark_birthday_notified(birthday['user_id'], chat_id)
                
            except Exception as e:
                logger.error(f"Error sending birthday message: {e}")
        
        # Reset notification flags for next year (global reset)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%m-%d")
        await self.db.reset_birthday_notifications(yesterday)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        
        # Only work in groups
        if chat_type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("I only work in group chats.")
            return
        
        self.active_chats.add(chat_id)
        
        # Start random message scheduling
        await self.schedule_random_messages(context, chat_id)
        
        # Schedule birthday checks - fixed time object creation
        birthday_time = datetime.now().time().replace(hour=9, minute=0, second=0, microsecond=0)
        
        # Remove existing birthday job first
        old_birthday_jobs = context.job_queue.get_jobs_by_name(f"birthday_check_{chat_id}")
        for job in old_birthday_jobs:
            job.schedule_removal()
        
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
        keyboard = [
            [InlineKeyboardButton("Set Birthday", callback_data="set_birthday")],
            [InlineKeyboardButton("View Birthdays", callback_data="view_birthdays")],
            [InlineKeyboardButton("Send Random Message", callback_data="send_random")],
            [InlineKeyboardButton("Info", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📋 Menu:",
            reply_markup=reply_markup
        )

    async def birthday_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Check if bot works only in groups
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("This command only works in group chats.")
            return
        
        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /birthday MM-DD\n"
                "Example: /birthday 03-15"
            )
            return
        
        user_id = update.message.from_user.id
        chat_id = update.effective_chat.id
        date_input = context.args[0].strip()
        
        try:
            # Validate date format
            if '-' not in date_input:
                raise ValueError("Invalid format")
                
            parts = date_input.split('-')
            if len(parts) != 2:
                raise ValueError("Invalid format")
                
            month, day = map(int, parts)
            
            # Validate month and day ranges
            if not (1 <= month <= 12):
                raise ValueError("Month must be between 1 and 12")
            if not (1 <= day <= 31):
                raise ValueError("Day must be between 1 and 31")
            
            # Basic validation for days in month
            if month in [4, 6, 9, 11] and day > 30:
                raise ValueError("Invalid day for this month")
            if month == 2 and day > 29:
                raise ValueError("Invalid day for February")
            
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
        if not message or not message.photo:
            return
            
        user_id = message.from_user.id
        chat_id = update.effective_chat.id
        
        # Check if user has a birthday in this chat but no baby photo yet
        birthday = await self.db.get_user_birthday(user_id, chat_id)
        
        if birthday and not birthday['baby_photo_file_id']:
            # Save baby photo for this specific chat
            file_id = message.photo[-1].file_id
            await self.db.update_baby_photo(user_id, chat_id, file_id)
            
            await message.reply_text("📸 Baby photo saved for birthday celebrations!")
        
        # Always store the photo as a regular message too
        await self.store_message(update, context)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        
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
        # Check if bot works only in groups
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
        """Debug command to check database status"""
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await update.message.reply_text("This command only works in group chats.")
            return
        
        chat_id = update.effective_chat.id
        message_count = await self.db.count_messages(chat_id)
        
        # Get some recent messages to check
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
                debug_info += f"- {msg['username']} ({msg['message_type']}) at {timestamp}\n"
        else:
            debug_info += "No messages found in database.\n"
        
        await update.message.reply_text(debug_info)

    def run(self):
        application = Application.builder().token(self.token).build()
        
        # Set bot commands for the / menu
        async def post_init(app):
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
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("menu", self.menu_command))
        application.add_handler(CommandHandler("birthday", self.birthday_command))
        application.add_handler(CommandHandler("random", self.random_command))
        application.add_handler(CommandHandler("debug", self.debug_command))
        
        # Button callback handler
        application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # Photo handler - should be before general message handler
        application.add_handler(MessageHandler(
            filters.PHOTO & filters.ChatType.GROUPS,
            self.handle_photo
        ))
        
        # General message handler - IMPORTANT: This needs to catch all group messages
        application.add_handler(MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            self.store_message
        ))
        
        logger.info("Minimal Memory Bot starting...")
        application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # IMPORTANT: Replace with your actual bot token
    BOT_TOKEN = "8020313173:AAGm5R7rgX6DR5qhkCuVZpjgX9853lnmAMg"
    
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Please set your bot token!")
        exit(1)
    
    try:
        bot = MinimalMemoryBot(BOT_TOKEN)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        print("Bot stopped gracefully")