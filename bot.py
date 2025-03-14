"""
Lidl Scraper Bot - Main Entry Point
This modular implementation separates concerns into dedicated modules
for better maintainability and organization.
"""
import logging
import asyncio
import re
import signal
import sys
import argparse
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from config import TOKEN
import database
from modules.scheduler import TaskScheduler
from modules.query_processor import convert_lidl_url_to_api
from modules.bot_commands import (
    start, choose_language, menu, menu_callback_handler,
    list_queries, pause_query, pause_query_callback,
    resume_query, resume_query_callback,
    delete_query, delete_query_callback
)

# Configure logging with more verbose output
logging.basicConfig(
    level=logging.DEBUG,  # Verhoogd van INFO naar DEBUG voor meer details
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("lidl_scraper.log"),
        logging.StreamHandler(sys.stdout)  # Expliciet uitvoer naar stdout
    ]
)
logger = logging.getLogger(__name__)

# Set telegram.ext logging to INFO for connection details
telegram_ext_logger = logging.getLogger('telegram.ext')
telegram_ext_logger.setLevel(logging.INFO)

# Global app instance
app = None

# URL and query handling
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle normal text messages from users."""
    user = update.effective_user
    text = update.message.text
    logger.info(f"BERICHT ONTVANGEN van {user.username} ({user.id}): {text}")
    
    # Handle query name input
    if context.user_data.get("await_queryname"):
        logger.debug("Verwerken van query naam input")
        await handle_query_name_input(update, context)
        return

    # Handle URLs
    if "https://" in text:
        logger.debug("URL gedetecteerd in bericht")
        await handle_url_input(update, context)
        return
    
    # Log dat het bericht niet werd verwerkt
    logger.debug("Bericht is geen URL en geen query naam input - geen actie ondernomen")

async def handle_query_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processing query name input: {update.message.text}")
    chat_id = str(update.effective_chat.id)
    query_name = update.message.text
    api_query = context.user_data.get("pending_query")

    if not api_query:
        await update.message.reply_text("Er ging iets mis. Probeer de URL opnieuw te plakken.")
        context.user_data["await_queryname"] = False
        return

    # Gebruik de database service om de query toe te voegen
    try:
        # Gebruik de database service methode rechtstreeks
        db = database.db_service
        success, message = db.add_query_for_chat_id(chat_id, query_name, api_query)
        await update.message.reply_text(message)
    except Exception as e:
        logger.exception(f"Error saving query: {e}")
        await update.message.reply_text("Er ging iets mis bij het opslaan van de query.")

    context.user_data["pending_query"] = None
    context.user_data["await_queryname"] = False

async def handle_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processing URL input: {update.message.text}")
    text = update.message.text
    context.user_data["pending_query"] = convert_lidl_url_to_api(text)
    
    # Show inline Yes/No buttons
    keyboard = [
        [
            InlineKeyboardButton("Ja", callback_data="confirm_query"),
            InlineKeyboardButton("Nee", callback_data="cancel_query")
        ]
    ]
    await update.message.reply_text(
        text=f"URL gevonden:\n{context.user_data['pending_query']}\nWil je deze toevoegen?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def confirm_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Confirm query callback triggered")
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Geef de naam voor deze zoekopdracht:")
    context.user_data["await_queryname"] = True

async def cancel_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cancel query callback triggered")
    query = update.callback_query
    await query.answer()
    context.user_data["pending_query"] = None
    context.user_data["await_queryname"] = False
    await query.edit_message_text("Toevoegen afgebroken.")

def register_handlers(application):
    """Register all handlers with the application.""" 
    logger.debug("Registreren van callback handlers...")
    
    application.add_handler(CallbackQueryHandler(choose_language, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(confirm_query_callback, pattern="^confirm_query$"))
    application.add_handler(CallbackQueryHandler(cancel_query_callback, pattern="^cancel_query$"))
    application.add_handler(CallbackQueryHandler(delete_query_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(pause_query_callback, pattern="^pause_"))
    application.add_handler(CallbackQueryHandler(resume_query_callback, pattern="^resume_"))


    # Command handlers come next
    logger.debug("Registreren van commando handlers...")
    
    application.add_handler(CommandHandler("start", start))
    logger.debug("Handler voor /start geregistreerd")
    
    application.add_handler(CommandHandler("menu", menu))
    logger.debug("Handler voor /menu geregistreerd")
    
    application.add_handler(CommandHandler("list", list_queries))
    application.add_handler(CommandHandler("pause", pause_query))
    application.add_handler(CommandHandler("resume", resume_query))
    application.add_handler(CommandHandler("delete", delete_query))

    # Text handler for everything else
    logger.debug("Registreren van text message handler...")
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    logger.info("Alle handlers succesvol geregistreerd!")

def main():
    """Main function to start the bot."""
    parser = argparse.ArgumentParser(description='Lidl Scraper Bot')
    parser.add_argument('--db-path', type=str, required=True,
                        help='Path to the database file (required)')
    args = parser.parse_args()
    
    db_path = args.db_path
    if not db_path:
        logger.critical("Database path (--db-path) is required")
        sys.exit(1)

    # Initialize database
    try:
        logger.info(f"Database initialiseren op pad: {db_path}")
        database.init_db(db_path)
        logger.info(f"Database succesvol geïnitialiseerd op: {db_path}")
        
        # Initialize the global db_service instance with the correct path
        database.db_service = database.DatabaseService(db_path)
        logger.info("Database service geïnitialiseerd")
    except Exception as e:
        logger.critical(f"Database initialisatie mislukt: {e}")
        sys.exit(1)
    
    # Initialize the global app variable
    global app
    logger.info(f"Bot initialiseren met token: {TOKEN[:5]}...{TOKEN[-5:] if len(TOKEN) > 10 else ''}")
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Register handlers
    register_handlers(app)
    
    # Create and configure scheduler
    scheduler = TaskScheduler(app)
    
    # Flag for shutdown
    shutdown_requested = False
    
    def signal_handler(signum, frame):
        """Handle shutdown signals by setting the flag"""
        nonlocal shutdown_requested
        logger.info(f"Shutdown signaal ontvangen: {signum}")
        shutdown_requested = True
    
    async def start_app():
        """Start the application and scheduler."""
        nonlocal shutdown_requested
        
        try:
            # Setup signal handlers - using traditional signal.signal for Windows compatibility
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Start the application
            logger.info("Bot applicatie initialiseren...")
            await app.initialize()
            await app.start()
            
            # Start the scheduler
            logger.info("Scheduler starten...")
            await scheduler.start()
            
            # Start polling with more robust settings for containerized environments
            logger.info("Starten met polling voor Telegram updates...")
            await app.updater.start_polling(
                poll_interval=2.0,            # Check more frequently
                timeout=30,                   # Longer timeout for slower connections
                bootstrap_retries=5,          # Retry bootstrap more times
                read_timeout=30,              # Longer read timeout
                write_timeout=30,             # Longer write timeout
                connect_timeout=30,           # Longer connect timeout
                pool_timeout=30,              # Longer pool timeout
                drop_pending_updates=True,    # Start fresh when the bot starts
                allowed_updates=["message", "callback_query", "chat_member"]  # Specify needed updates
            )
            
            # Log network diagnostics when running in container environment
            try:
                # Check if we're in a container environment
                in_container = os.path.exists("/.dockerenv") or os.environ.get("CONTAINER") == "true"
                if in_container:
                    logger.info("Running in container environment, checking network connectivity...")
                    import socket
                    # Test connection to Telegram API
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(5)
                    result = s.connect_ex(("api.telegram.org", 443))
                    if result == 0:
                        logger.info("Connection to api.telegram.org:443 successful")
                    else:
                        logger.error(f"Cannot connect to api.telegram.org:443, error code: {result}")
                    s.close()
            except Exception as e:
                logger.warning(f"Network diagnostic check failed: {e}")

            logger.info("BOT IS NU ACTIEF! Luistert naar berichten...")
            
            # Rest of the code remains the same...
            
            # Log a clear message to indicate the bot is running
            print("\n" + "="*50)
            print("🤖 LIDL SCRAPER BOT IS ACTIEF EN LUISTERT NAAR BERICHTEN!")
            print("="*50 + "\n")
            
            try:
                # Use simple sleep loop instead of event to avoid event loop issues
                while not shutdown_requested:
                    await asyncio.sleep(1)
            finally:
                # Ensure proper cleanup in correct order
                logger.info("Stopping scheduler...")
                await scheduler.stop()
                
                # Stop the updater first
                logger.info("Stopping updater...")
                await app.updater.stop()
                
                # Then stop the application
                logger.info("Stopping bot...")
                await app.shutdown()
                logger.info("Bot stopped")
        except Exception as e:
            logger.exception(f"Error in start_app: {e}")
            sys.exit(1)
    
    try:
        # Run the bot
        logger.info("Starting bot...")
        asyncio.run(start_app())
        logger.info("Bot has started.")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()