import os
import logging
import json
import sqlite3
from datetime import datetime, time, timedelta

# Import required libraries
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, JobQueue
)
from flask import Flask, request, abort

# --- CONFIGURATION (Hardcoded for immediate deployment) ---
# WARNING: Hardcoding your token is less secure than using environment variables.
# For security, you MUST replace 'YOUR_ACTUAL_BOT_TOKEN_HERE' with the token you got from BotFather.
BOT_TOKEN = "8020313173:AAG1V_ytdmVHCL7Jz0Y0MfGHgURe9G9pbnc" 

# The username is used for the log context
USERNAME = "blueberry111" 

WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://blueberry111.pythonanywhere.com{WEBHOOK_PATH}" 
# --- END CONFIGURATION ---

# Set up logging for PythonAnywhere debug
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Manager ---

class DatabaseManager:
    """Handles all SQLite database operations."""
    def __init__(self, db_path):
        self.db_path = db_path
        self._initialize_db()

    def _initialize_db(self):
        """Initializes the database connection and creates tables if they don't exist."""
        try:
            # Construct absolute path to ensure we always find the DB
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.db_path = os.path.join(script_dir, "bot_data.db")
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Stores message text and chat ID for the memory feature
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        username TEXT,
                        text TEXT NOT NULL,
                        timestamp TEXT NOT NULL
                    )
                """)
                # Stores birthdays
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS birthdays (
                        id INTEGER PRIMARY KEY,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL UNIQUE,
                        username TEXT,
                        name TEXT NOT NULL,
                        day INTEGER NOT NULL,
                        month INTEGER NOT NULL
                    )
                """)
                conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    # Data Storage Methods
    def store_message(self, chat_id, user_id, username, text):
        """Stores a message in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, user_id, username, text, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (chat_id, user_id, username, text, datetime.now().isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error storing message: {e}")

    def store_birthday(self, chat_id, user_id, username, name, day, month):
        """Stores or updates a user's birthday."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Use INSERT OR REPLACE to update if user_id already exists
                cursor.execute("""
                    INSERT OR REPLACE INTO birthdays (chat_id, user_id, username, name, day, month)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (chat_id, user_id, username, name, day, month))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error storing birthday: {e}")
            return False

    # Data Retrieval Methods
    def get_random_messages(self, chat_id, limit=1):
        """Retrieves a random message from the database for a specific chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT text, username, timestamp FROM messages 
                    WHERE chat_id = ? AND text NOT LIKE '/%'
                    ORDER BY RANDOM() LIMIT ?
                """, (chat_id, limit))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error retrieving random message: {e}")
            return []

    def get_birthdays_list(self, chat_id):
        """Retrieves all stored birthdays for a specific chat, ordered by month and day."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name, day, month FROM birthdays 
                    WHERE chat_id = ? 
                    ORDER BY month, day
                """, (chat_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error retrieving birthday list: {e}")
            return []

    def get_today_birthdays(self, month, day):
        """Retrieves birthdays matching the given day and month for all chats."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT chat_id, name, username FROM birthdays 
                    WHERE month = ? AND day = ?
                """, (month, day))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error retrieving today's birthdays: {e}")
            return []

    def count_messages(self, chat_id):
        """Counts total messages and fetches the 5 most recent for debug."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Count total messages
                cursor.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))
                count = cursor.fetchone()[0]
                
                # Fetch 5 most recent
                cursor.execute("""
                    SELECT text, username FROM messages 
                    WHERE chat_id = ?
                    ORDER BY timestamp DESC LIMIT 5
                """, (chat_id,))
                recent = cursor.fetchall()
                
                return count, recent
        except Exception as e:
            logger.error(f"Error counting messages: {e}")
            return 0, []

# --- Command Handlers ---

db = DatabaseManager(db_path="bot_data.db")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message with instructions."""
    if update.effective_chat.type == 'private':
        await update.message.reply_text(
            "Hello! I'm your group memory bot. Please add me to a group chat to start working.\n\n"
            "I will save all public messages and send random memories periodically, "
            "and remind you of birthdays!"
        )
    else:
        await update.message.reply_text(
            "Hi there! I'm now active in this group. I'll silently record messages "
            "to share memories later. Use /set_birthday to track important dates."
        )

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays memory status and latest entries for debug."""
    chat_id = update.effective_chat.id
    total_count, recent_messages = db.count_messages(chat_id)

    response = f"📚 **Memory Status for this Chat**\n"
    response += f"Total Messages Stored: **{total_count}**\n\n"
    
    if total_count > 0:
        response += "💾 **5 Most Recent Memories:**\n"
        for text, username in recent_messages:
            # Truncate text for display
            display_text = text[:40] + ('...' if len(text) > 40 else '')
            response += f"- @{username}: *{display_text}*\n"
    else:
        response += "The memory database is currently empty for this chat."

    await update.message.reply_markdown(response)

async def set_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the process of setting a birthday."""
    await update.message.reply_text(
        "To set a birthday, reply to this message with the date in **DD-MM-YYYY** format (e.g., 25-05-1990)."
    )

async def handle_birthday_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the reply to the /set_birthday command."""
    # Check if this message is a reply to the bot's message
    if update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot:
        if "To set a birthday" in update.message.reply_to_message.text:
            try:
                # Parse the date from the user's message
                date_str = update.message.text.split('-')
                if len(date_str) != 3:
                     raise ValueError("Incorrect format")

                day = int(date_str[0])
                month = int(date_str[1])
                # Year is ignored for birthday reminders but required for full date format
                year = int(date_str[2])

                # Basic validation
                if not 1 <= day <= 31 or not 1 <= month <= 12:
                    raise ValueError("Invalid day or month value")
                
                chat_id = update.effective_chat.id
                user_id = update.effective_user.id
                username = update.effective_user.username or update.effective_user.full_name
                name = update.effective_user.full_name

                if db.store_birthday(chat_id, user_id, username, name, day, month):
                    await update.message.reply_text(
                        f"🎉 Got it! **{name}'s** birthday is saved for **{day:02d}/{month:02d}**.",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text("I couldn't save the birthday due to a database error.")

            except (ValueError, IndexError):
                await update.message.reply_text(
                    "❌ I couldn't understand that date. Please ensure you use the **DD-MM-YYYY** format."
                )

async def view_birthdays_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays all stored birthdays for the current chat."""
    chat_id = update.effective_chat.id
    birthdays = db.get_birthdays_list(chat_id)

    if not birthdays:
        await update.message.reply_text("I haven't recorded any birthdays for this group yet.")
        return

    response = "🎂 **Group Birthdays (Month/Day):**\n"
    current_month = None
    
    for name, day, month in birthdays:
        if month != current_month:
            current_month = month
            response += f"\n**--- {datetime(2000, month, 1).strftime('%B')} ---**\n"
        
        response += f"- **{day:02d}**: {name}\n"

    await update.message.reply_markdown(response)


async def random_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retrieves a random message from the database."""
    chat_id = update.effective_chat.id
    messages = db.get_random_messages(chat_id)
    
    if messages:
        text, username, timestamp_str = messages[0]
        timestamp = datetime.fromisoformat(timestamp_str)
        
        reply_text = (
            f"🕰️ {timestamp.strftime('%B %d, %Y')}:\n"
            f"**@{username} said:**\n"
            f"> {text}"
        )
        await update.message.reply_markdown(reply_text)
    else:
        await update.message.reply_text("I haven't collected enough memories in this chat yet. Keep chatting!")


async def collect_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collects and stores messages that are not commands."""
    if update.message and update.message.text:
        text = update.message.text
        # Ignore private chats and messages that are commands
        if update.effective_chat.type in ['group', 'supergroup'] and not text.startswith('/'):
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            username = update.effective_user.username or update.effective_user.full_name
            db.store_message(chat_id, user_id, username, text)
            # Log successful collection (optional, useful for debugging)
            # logger.info(f"Collected message in chat {chat_id}")
    
    # Check for birthday reply in group chats
    await handle_birthday_reply(update, context)

# --- Scheduled Jobs ---

async def birthday_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a reminder for today's birthdays."""
    now = datetime.now()
    today_birthdays = db.get_today_birthdays(now.month, now.day)
    
    if not today_birthdays:
        return

    # Group birthdays by chat_id
    birthdays_by_chat = {}
    for chat_id, name, username in today_birthdays:
        if chat_id not in birthdays_by_chat:
            birthdays_by_chat[chat_id] = []
        birthdays_by_chat[chat_id].append(name)
        
    for chat_id, names in birthdays_by_chat.items():
        if len(names) == 1:
            message = f"🎂 **Happy Birthday to {names[0]}!** Let's make their day special!"
        else:
            names_str = ', '.join(names)
            message = f"🎉 **It's a birthday party!** Wishing a great day to: {names_str}!"
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=message, 
            parse_mode='Markdown'
        )

async def random_memory_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a random message to all chats found in the database."""
    # This retrieves all unique chat IDs that have stored messages
    try:
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT chat_id FROM messages")
            chat_ids = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get unique chat IDs for memory job: {e}")
        return

    for chat_id in chat_ids:
        messages = db.get_random_messages(chat_id)
        
        if messages:
            text, username, timestamp_str = messages[0]
            timestamp = datetime.fromisoformat(timestamp_str)

            reply_text = (
                f"🌟 **Throwback Time!** A random memory from the past:\n"
                f"**{timestamp.strftime('%B %d, %Y')}**\n"
                f"**@{username} said:**\n"
                f"> {text}"
            )
            
            await context.bot.send_message(
                chat_id=chat_id, 
                text=reply_text, 
                parse_mode='Markdown'
            )

def setup_jobs(application: Application):
    """Sets up and starts the Job Queue."""
    # Ensure JobQueue runs on separate thread/process than the webhook
    job_queue: JobQueue = application.job_queue

    # 1. Birthday Reminder (e.g., runs at 8:00 AM every day)
    job_queue.run_daily(
        birthday_reminder_job, 
        time=time(hour=8, minute=0, second=0),
        name="Birthday Reminder"
    )

    # 2. Random Memory Sender (e.g., runs every 6 hours)
    job_queue.run_repeating(
        random_memory_job, 
        interval=timedelta(hours=6), 
        first=time(hour=9, minute=0, second=0),
        name="Random Memory"
    )
    logger.info("Scheduled jobs initialized.")

# --- Flask Webhook Setup ---

# Create the core application instance
app = Flask(__name__)

# Initialize the PTB application object
application = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

# Setup handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("debug", debug_command))
application.add_handler(CommandHandler("set_birthday", set_birthday_command))
application.add_handler(CommandHandler("view_birthdays", view_birthdays_command))
application.add_handler(CommandHandler("random", random_message_command))
application.add_handler(MessageHandler(filters.ALL, collect_message))

# Setup scheduled jobs
setup_jobs(application)

@app.route('/')
def index():
    """Confirms the Flask application is running."""
    return "Hello from Flask & Python-Telegram-Bot! Webhook is active."

@app.route(WEBHOOK_PATH, methods=["POST"])
async def telegram_webhook_handler():
    """Receives updates from Telegram and passes them to PTB."""
    if request.method == "POST":
        try:
            # Get the JSON update from the request
            update_data = request.get_json(force=True)
            
            # Process the update with the PTB application
            update = Update.de_json(update_data, application.bot)
            await application.process_update(update)
            
            return "OK"
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            # Return 200 OK even on internal error to avoid Telegram sending the update again
            return "OK"
    
    # Telegram only sends POST requests to the webhook URL
    abort(405)


# This function is called by the WSGI file to run the app
def run():
    """The function that starts the application (called by WSGI)."""
    # The application is already built and handlers added above.
    # The Flask app 'app' is the entry point used by PythonAnywhere.
    logger.info("Flask/PTB application initialized and ready to receive webhooks.")

run()
