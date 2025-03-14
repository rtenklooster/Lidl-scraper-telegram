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
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

from config import TOKEN
import database
from modules.scheduler import TaskScheduler
from modules.bot_commands import (
    start, choose_language, menu, menu_callback_handler,
    list_queries, pause_query, pause_query_callback,
    resume_query, resume_query_callback,
    delete_query, delete_query_callback
)
from modules.query_processor import convert_lidl_url_to_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("lidl_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global app instance
app = None

# URL and query handling
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received text message: {update.message.text}")
    text = update.message.text

    # Handle query name input
    if context.user_data.get("await_queryname"):
        await handle_query_name_input(update, context)
        return

    # Handle URLs
    if "lidl.nl" in text:
        await handle_url_input(update, context)
        return

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
    # Callback handlers have priority
    application.add_handler(CallbackQueryHandler(choose_language, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(confirm_query_callback, pattern="^confirm_query$"))
    application.add_handler(CallbackQueryHandler(cancel_query_callback, pattern="^cancel_query$"))
    application.add_handler(CallbackQueryHandler(delete_query_callback, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(pause_query_callback, pattern="^pause_"))
    application.add_handler(CallbackQueryHandler(resume_query_callback, pattern="^resume_"))
    
    # Command handlers come next
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("list", list_queries))
    application.add_handler(CommandHandler("pause", pause_query))
    application.add_handler(CommandHandler("resume", resume_query))
    application.add_handler(CommandHandler("delete", delete_query))

    # Text handler for everything else
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

def main():
    """Main function to start the bot."""
    parser = argparse.ArgumentParser(description='Lidl Scraper Bot')
    parser.add_argument('--db-path', type=str, default=DATABASE_NAME, help='Path to the database file')
    args = parser.parse_args()

    # Initialize database
    database.init_db(args.db_path)
    
    # Initialize the global app variable
    global app
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Register handlers
    register_handlers(app)
    
    # Create and configure scheduler
    scheduler = TaskScheduler(app)
    
    # Event voor graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Shutdown signal received: {signum}")
        # We need to use call_soon_threadsafe because signal handlers run in a different thread
        asyncio.get_event_loop().call_soon_threadsafe(shutdown_event.set)
    
    async def start_app():
        """Start the application and scheduler."""
        try:
            # Setup signal handlers - using traditional signal.signal for Windows compatibility
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Start the application
            await app.initialize()
            await scheduler.start()
            
            # Start polling for updates
            await app.updater.start_polling()
            
            try:
                # Wait for shutdown signal
                await shutdown_event.wait()
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
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()