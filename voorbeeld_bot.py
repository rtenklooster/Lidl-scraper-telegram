# Import filters correctly for newer python-telegram-bot versions
import logging
import os
import sys
import asyncio
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
import db, configuration_values, requests
from pyVinted import Vinted, requester
from traceback import print_exc
from asyncio import queues
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from configuration_values import logger
import datetime

VER = "0.5.2.3"

# Restart function
def restart_script():
    """Restart the current script."""
    os.execv(sys.executable, ['python'] + sys.argv)



logger.info("Bot is starting up...")

# verify if bot still running
async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f'Hello {update.effective_user.first_name}')


# add a keyword to the db
async def add_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    args = context.args
    if not args:
        await update.message.reply_text('Usage: /add_query <url> [label]')
        return
    
    query = args[0]
    label = ' '.join(args[1:]) if len(args) > 1 else ''
    
    # Parse the URL and extract the query parameters
    parsed_url = urlparse(query)
    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params['order'] = ['newest_first']
    # Remove time and search_id if provided
    query_params.pop('time', None)
    query_params.pop('search_id', None)

    searched_text = query_params.get('search_text')

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    query = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment))

    # Some queries are made with filters only, so we need to check if the search_text is present
    if searched_text is None and db.is_query_in_db(query, chat_id) is True:
        await update.message.reply_text(f'Query already exists.')
    elif searched_text is not None and db.is_query_in_db(searched_text[0], chat_id) is True:
        await update.message.reply_text(f'Query already exists.')
    else:
        db.add_query_to_db(query, chat_id, label)
        db.log_query_added(chat_id, username)  # Log toevoegen
        query_list = format_queries(chat_id)
        await update.message.reply_text(f'Query added with label: {label}\nCurrent queries:\n{query_list}')


# remove a query from the db
async def remove_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    queries = db.get_queries(chat_id)
    
    if not queries:
        await update.message.reply_text('No queries to remove.')
        return
    
    keyboard = []
    for i, query in enumerate(queries):
        label = query[1] if query[1] else "Unnamed query"
        # We use "remove_" prefix to distinguish from other callbacks
        keyboard.append([InlineKeyboardButton(label, callback_data=f"remove_{i+1}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Select query to remove:',
        reply_markup=reply_markup
    )


# get all keywords from the db
async def queries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    query_list = format_queries(chat_id)
    if query_list:
        await update.message.reply_text(f'Current queries:\n{query_list}')
    else:
        await update.message.reply_text('No queries found.')


def format_queries(chat_id: str) -> str:
    all_queries = db.get_queries(chat_id)
    if not all_queries:
        return ""
    formatted = []
    for i, query in enumerate(all_queries):
        label = query[1] if query[1] else "Unnamed query"
        query_str = f"{i+1}. {label}"
        if query[2]:  # if is_paused
            query_str += " [PAUSED]"
        formatted.append(query_str)
    return "\n".join(formatted)


async def create_allowlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db.create_allowlist()
    await update.message.reply_text(f'Allowlist created. Add countries by using /add_country "FR,BE,ES,IT,LU,DE etc."')


async def delete_allowlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db.delete_allowlist()
    await update.message.reply_text(f'Allowlist deleted. All countries are allowed.')


async def add_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    country = context.args
    if not country:
        await update.message.reply_text('No country provided')
        return
    # remove spaces
    country = ' '.join(country).replace(" ", "")
    if len(country) != 2:
        await update.message.reply_text('Invalid country code')
        return
    # if already in allowlist
    if country.upper() in (country_list := db.get_allowlist()):
        await update.message.reply_text(f'Country "{country.upper()}" already in allowlist. Current allowlist: {country_list}')
    else:
        db.add_to_allowlist(country.upper())
        await update.message.reply_text(f'Done. Current allowlist: {db.get_allowlist()}')


async def remove_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    country = context.args
    if not country:
        await update.message.reply_text('No country provided')
        return
    # remove spaces
    country = ' '.join(country).replace(" ", "")
    if len(country) != 2:
        await update.message.reply_text('Invalid country code')
        return
    db.remove_from_allowlist(country.upper())
    await update.message.reply_text(f'Done. Current allowlist: {db.get_allowlist()}')


async def allowlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if db.get_allowlist() == 0:
        await update.message.reply_text(f'No allowlist set. All countries are allowed.')
    else:
        await update.message.reply_text(f'Current allowlist: {db.get_allowlist()}')


async def send_new_post(content, url, text, chat_id):
    async with bot:
        await bot.send_message(chat_id, content, parse_mode="HTML", read_timeout=20,
                               write_timeout=20,
                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text=text, url=url)]]))
        # Item ID uit URL halen
        item_id = url.split('/')[-1].split('-')[0] if '-' in url.split('/')[-1] else url.split('/')[-1]
        # Log notificatie
        db.log_notification_sent(chat_id, None, item_id)


def get_user_country(profile_id):
    # Users are shared between all Vinted platforms, so we can use any of them
    url = f"https://www.vinted.fr/api/v2/users/{profile_id}?localize=false"
    response = requester.get(url)
    # That's a LOT of requests, so if we get a 429 we wait a bit before retrying once
    if response.status_code == 429:
        # In case of rate limit, we're switching the endpoint. This one is slower, but it doesn't RL as soon. 
        # We're limiting the items per page to 1 to grab as little data as possible
        url = f"https://www.vinted.fr/api/v2/users/{profile_id}/items?page=1&per_page=1"
        response = requester.get(url)
        try:
            user_country = response.json()["items"][0]["user"]["country_iso_code"]
        except KeyError:
            print("Couldn't get the country due to too many requests. Returning default value.")
            user_country = "XX"
    else:
        user_country = response.json()["user"]["country_iso_code"]
    return user_country


async def process_items():
    max_retries = 3
    retry_count = 0

    try:
        # Haal alle queries op van alle gebruikers
        all_chat_ids = db.get_all_chat_ids()
        all_queries = {}  # Dict om unieke queries bij te houden
        query_subscribers = {}  # Dict om bij te houden welke gebruikers welke query volgen
        
        # Verzamel alle unieke queries en hun abonnees
        for chat_id in all_chat_ids:
            # Skip if user is globally paused
            if db.is_user_paused(chat_id):
                continue
                
            queries = db.get_queries(chat_id)
            for query_row in queries:
                query, label, is_paused = query_row[0:3]
                # Skip if query is paused
                if is_paused:
                    continue
                    
                # Voeg de query toe aan onze ontdubbelde lijst
                if query not in all_queries:
                    all_queries[query] = None
                    query_subscribers[query] = []
                
                # Voeg deze gebruiker toe als abonnee van deze query
                query_subscribers[query].append(chat_id)
        
        # Nu hebben we een unieke lijst met queries en weten we welke gebruikers geïnteresseerd zijn in elke query
        vinted = Vinted()
        # Verwerk elke unieke query slechts één keer
        for query, _ in all_queries.items():
            try:
                data = vinted.items.search(query)
                logger.info(f"Query: {query}, Results: {len(data)}")
                
                # Log successful API request
                db.log_api_request(query, 'success')
                
                # Stuur de resultaten naar alle geabonneerde gebruikers
                for chat_id in query_subscribers[query]:
                    await items_queue.put((data, False, query, chat_id))
                    db.update_query_processed(query, chat_id)
                    
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 401:
                    logger.error(f"Unauthorized error for query '{query}' for chat_id {chat_id}: {str(e)}")
                    
                    # Log failed API request
                    db.log_api_request(query, 'failed', e.response.status_code, str(e))
                    
                    # Attempt to refresh cookies and retry
                    requester.setCookies()  # Use requester.setCookies() instead of vinted.refresh_cookies()
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error("Max retries reached. Restarting script...")
                        restart_script()
                    try:
                        # Log retry API request
                        db.log_api_request(query, 'retry')
                        
                        data = vinted.items.search(query)
                        
                        # Log successful retry
                        db.log_api_request(query, 'success')
                        
                        # Stuur de resultaten naar alle geabonneerde gebruikers
                        for chat_id in query_subscribers[query]:
                            await items_queue.put((data, False, query, chat_id))
                            db.update_query_processed(query, chat_id)
                        retry_count = 0  # Reset retry count on success
                    except Exception as retry_e:
                        logger.error(f"Retry failed for query '{query}' for chat_id {chat_id}: {str(retry_e)}")
                        
                        # Log failed retry
                        db.log_api_request(query, 'failed', None, str(retry_e))
                elif e.response.status_code == 429:
                    logger.warning(f"Rate limiting detected for query '{query}'. Wachten voor volgende poging...")
                    
                    # Log rate limit
                    db.log_api_request(query, 'failed', e.response.status_code, "Rate limit exceeded")
                    
                    # Wacht even voor de volgende poging
                    await asyncio.sleep(60)
                else:
                    logger.error(f"Error processing query '{query}' for chat_id {chat_id}: {str(e)}")
                    
                    # Log failed API request with status code
                    db.log_api_request(query, 'failed', e.response.status_code, str(e))
            except Exception as e:
                logger.error(f"Error processing query '{query}' for chat_id {chat_id}: {str(e)}")
                
                # Log failed API request
                db.log_api_request(query, 'failed', None, str(e))
                continue
    except Exception as e:
        logger.error(f"Error in process_items: {str(e)}")


async def background_worker(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now()
    if 7 <= now.hour < 22 or (now.hour == 22 and now.minute <= 30):
        try:
            await process_items()
        except Exception as e:
            logger.error(f"Error in process_items: {str(e)}")
    else:
        logger.info("Skipping process_items because it's outside the allowed hours (07:00 - 22:30).")


async def check_version(context: ContextTypes.DEFAULT_TYPE):
    # get latest version from the repository
    url = f"https://github.com/Fuyucch1/Vinted-Notifications/releases/latest"
    response = requests.get(url)

    if response.status_code == 200:
        if VER != response.url.split('/')[-1]:
            await send_new_post("A new version is available, please update the bot.", url, "Open Github")


async def clean_db(context: ContextTypes.DEFAULT_TYPE):
    db.clean_db()


async def clear_telegram_queue(context: ContextTypes.DEFAULT_TYPE):
    while 1:
        content, url, text = await new_items_queue.get()
        await send_new_post(content, url, text)


async def clear_item_queue(context: ContextTypes.DEFAULT_TYPE = None):
    """
    Process queued items and send notifications
    Args:
        context: The context passed by the job queue (optional)
    """
    while True:
        try:
            # Unpack all 4 values: data, processed flag, query, and chat_id
            data, already_processed, query, chat_id = await items_queue.get()
            
            if not data:
                continue
                
            for item in data:
                try:
                    # Access item properties as object attributes
                    item_id = item.id
                    if not db.is_item_in_db(item_id, chat_id):  # <- Geef chat_id mee
                        db.add_item_to_db(item_id, query, chat_id)
                        content = configuration_values.MESSAGE.format(
                            title=item.title,
                            price=item.price,
                            brand=getattr(item, 'brand_title', 'No Brand'),
                            status=item.raw_data.get('status', 'Onbekend'),
                            size=getattr(item, 'size_title', 'Onbekend'),
                            image=item.photo
                        )
                        await send_new_post(content, item.url, "Kijk snel!", chat_id)
                        
                except Exception as e:
                    logger.error(f"Error processing item: {str(e)}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error in clear_item_queue: {str(e)}")
            await asyncio.sleep(1)  # Add small delay to prevent tight loop on errors
            continue


async def set_commands(context: ContextTypes.DEFAULT_TYPE):
    await bot.set_my_commands([
        ("hello", "Kijk of de bot werkt"),
        ("add_query", "Zoekopdracht toevoegen"),
        ("remove_query", "Zoekopdracht verwijderen"),
        ("queries", "Zoekopdrachten weergeven"),
        ("pause", "Pauzeer alle zoekopdrachten"),
        ("resume", "Hervat alle zoekopdrachten"),
        #("create_allowlist", "Create an allowlist"),
        #("delete_allowlist", "Delete the allowlist"),
        #("add_country", "Add a country to the allowlist"),
        #("remove_country", "Remove a country from the allowlist"),
        #("allowlist", "List all countries in the allowlist"),
        ("pause_query", "Pauzeer specifieke zoekopdracht"),
        ("resume_query", "Hervat gepauzeerde zoekopdracht"),
        ("reboot", "Herstart de bot")
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    username = update.effective_user.username
    db.add_user(chat_id, username)
    db.log_bot_started(chat_id)  # Log bot start
    await update.message.reply_text(
        f'Welcome {username}! You can now add queries using /add_query command.'
    )


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pause notifications for the user"""
    if not update.effective_message:
        return
        
    chat_id = str(update.effective_chat.id)
    if db.is_user_paused(chat_id):
        await update.effective_message.reply_text('Notifications are already paused.')
        return
        
    if db.pause_user(chat_id):
        await update.effective_message.reply_text('Notifications paused. Use /resume to start receiving notifications again.')
    else:
        await update.effective_message.reply_text('Failed to pause notifications. Please try again.')

async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume notifications for the user"""
    chat_id = str(update.effective_chat.id)
    if not db.is_user_paused(chat_id):
        await update.message.reply_text('Notifications are not paused.')
        return
        
    if db.resume_user(chat_id):
        await update.message.reply_text('Notifications resumed. You will start receiving updates again.')
    else:
        await update.message.reply_text('Failed to resume notifications. Please try again.')

async def pause_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    queries = db.get_queries(chat_id)
    
    # Filter to only show active (not paused) queries
    active_queries = [q for q in queries if not q[2]]
    
    if not active_queries:
        await update.message.reply_text('No active queries to pause.')
        return
    
    keyboard = []
    for i, query in enumerate(queries):
        if not query[2]:  # Only show if not paused
            label = query[1] if query[1] else "Unnamed query"
            # Store the original index+1 as the query_number
            keyboard.append([InlineKeyboardButton(label, callback_data=f"pause_{i+1}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Select query to pause:',
        reply_markup=reply_markup
    )

async def resume_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    queries = db.get_queries(chat_id)
    
    # Filter to only show paused queries
    paused_queries = [q for q in queries if q[2]]
    
    if not paused_queries:
        await update.message.reply_text('No paused queries to resume.')
        return
    
    keyboard = []
    for i, query in enumerate(queries):
        if query[2]:  # Only show if paused
            label = query[1] if query[1] else "Unnamed query"
            # Store the original index+1 as the query_number
            keyboard.append([InlineKeyboardButton(label, callback_data=f"resume_{i+1}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Select query to resume:',
        reply_markup=reply_markup
    )

# Handler for messages without specific commands
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
        # Handle other messages or just ignore them
        pass

# Handler for user responses to the query addition prompt
async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    chat_id = str(update.effective_chat.id)

    if 'pending_query' in context.user_data and 'awaiting_label' in context.user_data:
        label = message_text
        query = context.user_data.pop('pending_query')
        context.user_data.pop('awaiting_label', None)
        await add_query_with_label(update, context, query, label)

async def add_query_with_label(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, label: str) -> None:
    chat_id = str(update.effective_chat.id)
    
    # Parse the URL and extract the query parameters
    parsed_url = urlparse(query)
    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params['order'] = ['newest_first']
    # Remove time and search_id if provided
    query_params.pop('time', None)
    query_params.pop('search_id', None)

    searched_text = query_params.get('search_text')

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    query = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment))

    # Some queries are made with filters only, so we need to check if the search_text is present
    if searched_text is None and db.is_query_in_db(query, chat_id) is True:
        await update.message.reply_text(f'Query already exists.')
    elif searched_text is not None and db.is_query_in_db(searched_text[0], chat_id) is True:
        await update.message.reply_text(f'Query already exists.')
    else:
        db.add_query_to_db(query, chat_id, label)
        query_list = format_queries(chat_id)
        await update.message.reply_text(f'Query added with label: {label}\nCurrent queries:\n{query_list}')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    chat_id = str(update.effective_chat.id)
    callback_data = query.data
    
    if callback_data == "query_yes":
        await query.edit_message_text(text="Please provide a name for the query.")
        context.user_data['awaiting_label'] = True
    elif callback_data == "query_no":
        if 'pending_query' in context.user_data:
            context.user_data.pop('pending_query', None)
        await query.edit_message_text(text="Query addition cancelled.")
    elif callback_data.startswith("pause_"):
        try:
            query_number = int(callback_data.split("_")[1])
            if db.pause_query(query_number, chat_id):
                db.log_query_paused(chat_id)  # Log pauzeren
                query_list = format_queries(chat_id)
                await query.edit_message_text(f'Query paused successfully.\nCurrent queries:\n{query_list}')
            else:
                await query.edit_message_text(f'Failed to pause query. Please try again.')
        except Exception as e:
            await query.edit_message_text(f'Error: {str(e)}')
    elif callback_data.startswith("resume_"):
        try:
            query_number = int(callback_data.split("_")[1])
            if db.resume_query(query_number, chat_id):
                db.log_query_resumed(chat_id)  # Log hervatten
                query_list = format_queries(chat_id)
                await query.edit_message_text(f'Query resumed successfully.\nCurrent queries:\n{query_list}')
            else:
                await query.edit_message_text(f'Failed to resume query. Please try again.')
        except Exception as e:
            await query.edit_message_text(f'Error: {str(e)}')
    elif callback_data.startswith("remove_"):
        try:
            query_number = int(callback_data.split("_")[1])
            # We need to get the actual query from the database
            queries = db.get_queries(chat_id)
            if 0 < query_number <= len(queries):
                query_to_remove = queries[query_number-1][0]
                if db.remove_query_from_db(query_to_remove, chat_id):
                    db.log_query_removed(chat_id)  # Log verwijderen
                    query_list = format_queries(chat_id)
                    await query.edit_message_text(f'Query removed successfully.\nCurrent queries:\n{query_list}')
                else:
                    await query.edit_message_text(f'Failed to remove query. Please try again.')
            else:
                await query.edit_message_text(f'Invalid query number.')
        except Exception as e:
            await query.edit_message_text(f'Error: {str(e)}')
    elif callback_data.startswith("copy_"):
        try:
            # Ignore header and separator buttons
            if callback_data in ["header_no_action", "separator_no_action"]:
                return
                
            query_hash = callback_data.split("_")[1]
            
            # Get the actual query from stored data
            if 'copyable_queries' in context.user_data and query_hash in context.user_data['copyable_queries']:
                query_to_copy = context.user_data['copyable_queries'][query_hash]
                
                # Now ask for a label
                await query.edit_message_text("Please provide a name for this query:")
                context.user_data['pending_query'] = query_to_copy
                context.user_data['awaiting_label'] = True
            else:
                await query.edit_message_text("Query not found or expired. Please try again.")
                
        except Exception as e:
            await query.edit_message_text(f"Error copying query: {str(e)}")

async def reboot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restart the bot"""
    await update.message.reply_text('Rebooting the bot, please wait...')
    logger.info(f"Reboot initiated by user {update.effective_user.username} (ID: {update.effective_chat.id})")
    restart_script()

async def copy_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Copy a query from another user
    This command is hidden from the commands menu
    """
    chat_id = str(update.effective_chat.id)
    
    # Get all queries from all users except the current user
    all_queries = db.get_other_users_queries(chat_id)
    
    if not all_queries:
        await update.message.reply_text('No queries from other users found.')
        return
    
    # Group queries by username for better organization
    queries_by_user = {}
    for query, label, username in all_queries:
        if username not in queries_by_user:
            queries_by_user[username] = []
        # Use label if available, otherwise use shortened query
        display_name = label if label else query[:30] + "..." if len(query) > 30 else query
        queries_by_user[username].append((query, display_name))
    
    # Build keyboard with queries grouped by user
    keyboard = []
    for username, queries in queries_by_user.items():
        # Add username as a non-clickable button header
        keyboard.append([InlineKeyboardButton(f"@{username}'s queries:", callback_data="header_no_action")])
        # Add each query with callback data
        for i, (query, display_name) in enumerate(queries):
            # We encode the query in the callback_data
            # Format: copy_[query_hash]
            # We use a hash to avoid exceeding the 64 byte limit of callback_data
            query_hash = str(hash(query))
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"copy_{query_hash}")])
        
        # Add a separator between users
        if list(queries_by_user.keys()).index(username) < len(queries_by_user) - 1:
            keyboard.append([InlineKeyboardButton("---", callback_data="separator_no_action")])
    
    # Store the queries for retrieval in the callback
    context.user_data['copyable_queries'] = {str(hash(q[0])): q[0] for u in queries_by_user.values() for q in u}
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        'Select a query to copy:',
        reply_markup=reply_markup
    )

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    
    # Algemene statistieken
    overall_stats = db.get_user_statistics()
    if overall_stats:
        total_users, total_queries_added, total_queries_removed, total_queries_paused, total_queries_resumed, total_bot_starts = overall_stats
    else:
        total_users, total_queries_added, total_queries_removed, total_queries_paused, total_queries_resumed, total_bot_starts = 0, 0, 0, 0, 0, 0
    
    # Gebruikersstatistieken
    user_stats = db.get_user_statistics(chat_id)
    if user_stats:
        username, queries_added, queries_removed, queries_paused, queries_resumed, bot_started_count, last_active = user_stats
    else:
        username, queries_added, queries_removed, queries_paused, queries_resumed, bot_started_count, last_active = "Onbekend", 0, 0, 0, 0, 0, "Nooit"
    
    # Notificatiestatistieken
    notification_stats = db.get_notification_statistics()
    if not notification_stats:
        notification_stats = {"last_3_hours": 0, "last_6_hours": 0, "last_12_hours": 0, "last_24_hours": 0}
    
    # Top gebruikers
    top_users = db.get_top_users(5)
    top_users_text = "\n".join([f"{i+1}. {user[0] or 'Onbekend'}: {user[1]} queries" for i, user in enumerate(top_users)]) if top_users else "Geen data"
    
    # API request statistieken
    api_stats = db.get_api_request_statistics()
    if not api_stats:
        api_stats = {
            "last_3_hours": {"unique_requests": 0, "successful": 0, "retries": 0, "failed": 0},
            "last_6_hours": {"unique_requests": 0, "successful": 0, "retries": 0, "failed": 0},
            "last_12_hours": {"unique_requests": 0, "successful": 0, "retries": 0, "failed": 0},
            "last_24_hours": {"unique_requests": 0, "successful": 0, "retries": 0, "failed": 0}
        }
    
    # Rapport formatteren
    report_text = f"""
📊 *Bot Statistieken Rapport* 📊

*Algemene Statistieken:*
👥 Totaal Gebruikers: {total_users}
📝 Totaal Queries Toegevoegd: {total_queries_added}
🗑️ Totaal Queries Verwijderd: {total_queries_removed}
⏸️ Totaal Queries Gepauzeerd: {total_queries_paused}
▶️ Totaal Queries Hervat: {total_queries_resumed}
🚀 Totaal Bot Starts: {total_bot_starts}

*Jouw Statistieken:*
👤 Gebruikersnaam: {username}
📝 Queries Toegevoegd: {queries_added}
🗑️ Queries Verwijderd: {queries_removed}
⏸️ Queries Gepauzeerd: {queries_paused}
▶️ Queries Hervat: {queries_resumed}
🚀 Bot Start Aantal: {bot_started_count}
⏱️ Laatst Actief: {last_active}

*Notificatie Statistieken:*
🔔 Laatste 3 Uur: {notification_stats["last_3_hours"]}
🔔 Laatste 6 Uur: {notification_stats["last_6_hours"]}
🔔 Laatste 12 Uur: {notification_stats["last_12_hours"]}
🔔 Laatste 24 Uur: {notification_stats["last_24_hours"]}

*API Request Statistieken:*
📊 *Laatste 3 uur:* 
   - Unieke requests: {api_stats["last_3_hours"]["unique_requests"]}
   - Succesvol: {api_stats["last_3_hours"]["successful"]}
   - Retries: {api_stats["last_3_hours"]["retries"]}
   - Mislukt: {api_stats["last_3_hours"]["failed"]}

📊 *Laatste 6 uur:* 
   - Unieke requests: {api_stats["last_6_hours"]["unique_requests"]}
   - Succesvol: {api_stats["last_6_hours"]["successful"]}
   - Retries: {api_stats["last_6_hours"]["retries"]}
   - Mislukt: {api_stats["last_6_hours"]["failed"]}

📊 *Laatste 12 uur:* 
   - Unieke requests: {api_stats["last_12_hours"]["unique_requests"]}
   - Succesvol: {api_stats["last_12_hours"]["successful"]}
   - Retries: {api_stats["last_12_hours"]["retries"]}
   - Mislukt: {api_stats["last_12_hours"]["failed"]}

📊 *Laatste 24 uur:* 
   - Unieke requests: {api_stats["last_24_hours"]["unique_requests"]}
   - Succesvol: {api_stats["last_24_hours"]["successful"]}
   - Retries: {api_stats["last_24_hours"]["retries"]}
   - Mislukt: {api_stats["last_24_hours"]["failed"]}

*Top Gebruikers op Basis van Queries:*
{top_users_text}
"""
    
    await update.message.reply_text(report_text, parse_mode="Markdown")

if not os.path.exists("vinted.db"):
    db.create_sqlite_db()
else:
    db.create_stats_tables()  # Zorg ervoor dat de statistiektabellen bestaan

bot = Bot(configuration_values.TOKEN)
app = ApplicationBuilder().token(configuration_values.TOKEN).build()

# Create the item queue to process
items_queue = queues.Queue()
# Create the item queue to send to telegram
new_items_queue = queues.Queue()

# Handler verify if bot is running
app.add_handler(CommandHandler("hello", hello))
# Keyword handlers
app.add_handler(CommandHandler("add_query", add_query))
app.add_handler(CommandHandler("remove_query", remove_query))
app.add_handler(CommandHandler("queries", queries))
# Allowlist handlers
#app.add_handler(CommandHandler("create_allowlist", create_allowlist))
#app.add_handler(CommandHandler("delete_allowlist", delete_allowlist))
#app.add_handler(CommandHandler("add_country", add_country))
#app.add_handler(CommandHandler("remove_country", remove_country))
#app.add_handler(CommandHandler("allowlist", allowlist))
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("pause", pause))
app.add_handler(CommandHandler("resume", resume))
app.add_handler(CommandHandler("pause_query", pause_query))
app.add_handler(CommandHandler("resume_query", resume_query))
app.add_handler(CommandHandler("reboot", reboot))
# Voeg dit toe bij de andere commandohandlers:
app.add_handler(CommandHandler("copy_query", copy_query))
app.add_handler(CommandHandler("report", report))
# Message handlers
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.add_handler(CallbackQueryHandler(button_callback))

# TODO : Help command

# TODO : Manage removals after current items have been processed.

job_queue = app.job_queue
# Every minute we check for new listings
job_queue.run_repeating(background_worker, interval=120, first=10)  # 120 seconden = 2 minuten
# Every day we check for a new version
job_queue.run_repeating(check_version, interval=86400, first=1)
# Every day we clean the db
job_queue.run_repeating(clean_db, interval=86400, first=1)
# Every second we send the posts to telegram
job_queue.run_once(clear_telegram_queue, when=1)
# Every second we process the items
job_queue.run_once(clear_item_queue, when=1)
# Set the commands
job_queue.run_once(set_commands, when=1)

print("Bot started. Head to your telegram and type /hello to check if it's running.")

app.run_polling()
