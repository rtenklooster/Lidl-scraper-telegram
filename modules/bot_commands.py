"""
Bot commands module handles all Telegram command interactions.
This module contains handlers for different commands like start, menu, etc.
"""
import logging
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database
from config import DATABASE_NAME

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command to initialize users."""
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    
    # Gebruik de database service
    db = database.db_service
    user = db.get_user_by_chat_id(chat_id)

    if not user:
        # New user registration
        keyboard = [
            [InlineKeyboardButton("Nederlands", callback_data="lang_nl"), 
             InlineKeyboardButton("English", callback_data="lang_en")]
        ]
        await update.message.reply_text(
            text="Welkom! Selecteer je taal / Please select your language:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        
        # Save user with default language
        db.register_new_user(chat_id, username)
    else:
        await update.message.reply_text("Welkom terug!")

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection callback."""
    query = update.callback_query
    await query.answer()
    lang_choice = query.data
    chat_id = str(query.message.chat_id)
    lang = "Nederlands" if "nl" in lang_choice else "English"

    # Gebruik de database service
    db = database.db_service
    db.update_user_language(chat_id, lang_choice[-2:])

    await query.edit_message_text(f"Taal is ingesteld op {lang}.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu with inline buttons for different actions."""
    keyboard = [
        [InlineKeyboardButton("📋 Zoekopdrachten weergeven", callback_data="menu_list_queries")],
        [InlineKeyboardButton("⏸️ Zoekopdracht pauzeren", callback_data="menu_pause_query")],
        [InlineKeyboardButton("▶️ Zoekopdracht hervatten", callback_data="menu_resume_query")],
        [InlineKeyboardButton("🗑️ Zoekopdracht verwijderen", callback_data="menu_delete_query")],
    ]
    await update.message.reply_text(
        text="Kies een actie:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process choices from the main menu."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "menu_list_queries":
        await query.edit_message_text("Je huidige zoekopdrachten:")
        await list_queries(update, context)

    elif choice == "menu_pause_query":
        await query.edit_message_text("Pauzeer een zoekopdracht:")
        await pause_query(update, context)

    elif choice == "menu_resume_query":
        await query.edit_message_text("Hervat een zoekopdracht:")
        await resume_query(update, context)

    elif choice == "menu_delete_query":
        # Voor het verwijderen hoeven we de tekst niet te wijzigen, maar direct de delete_query functie aanroepen
        # Dit voorkomt de 'NoneType' heeft geen 'reply_text' attribuut foutmelding
        await delete_query(update, context)

async def list_queries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all queries for the user."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else str(update.callback_query.message.chat_id)
    
    # Gebruik de database service
    db = database.db_service
    rows = db.get_queries_for_chat_id(chat_id)

    if not rows:
        message_text = "Geen zoekopdrachten gevonden."
    else:
        reply_lines = []
        for i, row in enumerate(rows, start=1):
            query_name = row[1] or f"Query #{row[0]}"
            interval_minutes = row[2]
            paused_status = "Gepauzeerd" if row[3] else "Actief"
            reply_lines.append(f"{i}. {query_name} | Interval: {interval_minutes}m | Status: {paused_status}")
        message_text = "\n".join(reply_lines)

    # Handle different update types
    if update.callback_query:
        await update.callback_query.message.reply_text(message_text)
    else:
        await update.message.reply_text(message_text)

async def pause_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause a query."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else str(update.callback_query.message.chat_id)
    
    # Gebruik de database service
    db = database.db_service
    rows = db.get_active_queries_for_chat_id(chat_id)

    if not rows:
        if update.effective_chat:
            await update.message.reply_text("Geen actieve zoekopdrachten om te pauzeren.")
        else:
            await update.callback_query.message.reply_text("Geen actieve zoekopdrachten om te pauzeren.")
        return

    # If there are multiple queries, show selection buttons
    if len(rows) > 1:
        keyboard = []
        for row in rows:
            query_id, query_name, query_text = row
            display_name = query_name or f"Query #{query_id}"
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"pause_{query_id}")])
        
        if update.effective_chat:
            await update.message.reply_text(
                "Selecteer welke zoekopdracht je wilt pauzeren:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.callback_query.message.reply_text(
                "Selecteer welke zoekopdracht je wilt pauzeren:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # If only one query, pause it directly
        query_id, query_name, query_text = rows[0]
        display_name = query_name or f"Query #{query_id}"
        db.pause_query(query_id)
        
        if update.effective_chat:
            await update.message.reply_text(f"Zoekopdracht '{display_name}' is gepauzeerd.")
        else:
            await update.callback_query.message.reply_text(f"Zoekopdracht '{display_name}' is gepauzeerd.")

async def pause_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for pause query selection."""
    query = update.callback_query
    await query.answer()
    
    # Extract query_id from callback data
    query_id = query.data.split("_")[1]
    
    # Gebruik de database service
    db = database.db_service
    query_name = db.get_query_name(query_id)
    
    if not query_name:
        await query.edit_message_text("Zoekopdracht niet gevonden.")
        return
    
    display_name = query_name or f"Query #{query_id}"
    db.pause_query(query_id)
    
    await query.edit_message_text(f"Zoekopdracht '{display_name}' is gepauzeerd.")

async def resume_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume a paused query."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else str(update.callback_query.message.chat_id)
    
    # Gebruik de database service
    db = database.db_service
    rows = db.get_paused_queries_for_chat_id(chat_id)

    if not rows:
        if update.effective_chat:
            await update.message.reply_text("Geen gepauzeerde zoekopdrachten om te hervatten.")
        else:
            await update.callback_query.message.reply_text("Geen gepauzeerde zoekopdrachten om te hervatten.")
        return

    # If there are multiple queries, show selection buttons
    if len(rows) > 1:
        keyboard = []
        for row in rows:
            query_id, query_name, query_text = row
            display_name = query_name or f"Query #{query_id}"
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"resume_{query_id}")])
        
        if update.effective_chat:
            await update.message.reply_text(
                "Selecteer welke zoekopdracht je wilt hervatten:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.callback_query.message.reply_text(
                "Selecteer welke zoekopdracht je wilt hervatten:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        # If only one query, resume it directly
        query_id, query_name, query_text = rows[0]
        display_name = query_name or f"Query #{query_id}"
        db.resume_query(query_id)
        
        if update.effective_chat:
            await update.message.reply_text(f"Zoekopdracht '{display_name}' is hervat.")
        else:
            await update.callback_query.message.reply_text(f"Zoekopdracht '{display_name}' is hervat.")

async def resume_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for resume query selection."""
    query = update.callback_query
    await query.answer()
    
    # Extract query_id from callback data
    query_id = query.data.split("_")[1]
    
    # Gebruik de database service
    db = database.db_service
    query_name = db.get_query_name(query_id)
    
    if not query_name:
        await query.edit_message_text("Zoekopdracht niet gevonden.")
        return
    
    display_name = query_name or f"Query #{query_id}"
    db.resume_query(query_id)
    
    await query.edit_message_text(f"Zoekopdracht '{display_name}' is hervat.")

async def delete_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a query."""
    chat_id = str(update.effective_chat.id) if update.effective_chat else str(update.callback_query.message.chat_id)
    
    # Gebruik de database service
    db = database.db_service
    rows = db.get_queries_for_chat_id(chat_id)

    if not rows:
        if update.callback_query:
            await update.callback_query.message.reply_text("Geen zoekopdrachten om te verwijderen.")
        elif update.message:
            await update.message.reply_text("Geen zoekopdrachten om te verwijderen.")
        return

    # Build inline buttons dynamically
    keyboard = []
    for row in rows:
        query_id = row[0]
        query_name = row[1] or f"Query #{query_id}"
        keyboard.append([InlineKeyboardButton(query_name, callback_data=f"delete_{query_id}")])

    message_text = "Kies een opdracht om te verwijderen:"
    
    # Controleer op een correcte manier of het een callback query is of een direct bericht
    if update.callback_query:
        await update.callback_query.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.message:
        await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete query selection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("delete_"):
        return

    query_id = data.split("_")[1]
    
    # Gebruik de database service
    db = database.db_service
    db.delete_query(query_id)

    await query.edit_message_text("Zoekopdracht is verwijderd.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    chat_id = str(update.effective_chat.id)

    # Check if we're waiting for a query label
    if 'awaiting_label' in context.user_data and 'pending_query' in context.user_data:
        label = message_text
        query = context.user_data.pop('pending_query')
        context.user_data.pop('awaiting_label')
        await add_query_with_label(update, context, query, label)
    # Check if the message contains a URL
    elif "http" in message_text:
        context.user_data['pending_query'] = message_text
        
        # Create inline keyboard with Yes and No buttons
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data="query_yes"),
                InlineKeyboardButton("No", callback_data="query_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            'Do you want to add this query?',
            reply_markup=reply_markup
        )
    else:
        # Handle other messages
        await update.message.reply_text("Sorry, I didn't understand that. Please send a valid URL.")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Combined handler for all text messages:
    - Processes URLs when relevant
    - Processes query names when expected
    """
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
    """Process query name input."""
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
    """Process URL input."""
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
    """Yes button clicked: ask for a name."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Geef de naam voor deze zoekopdracht:")
    context.user_data["await_queryname"] = True

async def cancel_query_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """No button clicked: cancel and clear pending_query."""
    query = update.callback_query
    await query.answer()
    context.user_data["pending_query"] = None
    context.user_data["await_queryname"] = False
    await query.edit_message_text("Toevoegen afgebroken.")