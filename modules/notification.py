"""
Notification Module
Handles generation and sending of notifications to users.
"""
import logging
from datetime import datetime
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
import database

logger = logging.getLogger(__name__)

async def notify_initial_query(app, query_id: int, query_name: str, result_count: int, chat_id: int):
    """
    Send a summary notification to the user when a query is executed for the first time.
    
    Args:
        app: The Telegram application instance for sending messages
        query_id: ID of the query
        query_name: Name of the query
        result_count: Number of results added to the database
        chat_id: Chat ID to send the notification to
    """
    message = f"Zoekopdracht: {query_name} is voor het eerst uitgevoerd. Er zijn {result_count} resultaten toegevoegd aan de database."
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=message,
            disable_web_page_preview=True
        )
        logger.info(f"Initial query notification sent to {chat_id}: {query_name} with {result_count} results")
    except Exception as e:
        logger.error(f"Failed to send initial query notification to {chat_id}: {e}")

async def notify_user(app, query_id: int, product_id: int = None, label: str = None, new_price: float = None, 
               old_price: float = None, product_url: str = None, image_url: str = None, notification_type: str = None,
               discount_amount: float = None, discount_percentage: float = None):
    """
    Send notification to user about a new product or price change.
    Includes discount information when available and price history.
    
    Args:
        app: The Telegram application instance for sending messages
        query_id: ID of the query
        product_id: ID of the product in database
        label: Name of the product
        new_price: New price of the product
        old_price: Old price of the product (if available)
        product_url: URL to the product
        image_url: URL to the product image
        notification_type: Type of notification ('new_product', 'price_drop', 'price_increase')
        discount_amount: Discount amount (if available)
        discount_percentage: Discount percentage (if available)
    """
    # Gebruik de database service in plaats van directe verbindingen
    db = database.db_service
    
    # Get user information
    user_id, chat_id = db.get_user_for_query(query_id)
    
    # If we couldn't get user_id or chat_id, we can't continue
    if not user_id or not chat_id:
        logger.error(f"Could not retrieve user_id or chat_id for notification. Query ID: {query_id}")
        return
    
    # Check if this is the initial execution of the query
    if db.is_initial_query_execution(query_id):
        query_name = db.get_query_name(query_id) or f"Query #{query_id}"
        result_count = db.get_result_count_for_query(query_id)
        await notify_initial_query(app, query_id, query_name, result_count, chat_id)
        return
    
    # If new product but product_id not provided, try to look it up
    if notification_type == "new_product" and not product_id and label:
        product_id = db.find_product_id_by_label(query_id, label)
    
    # Get query name
    query_name = db.get_query_name(query_id) or f"Query #{query_id}"
    
    # Get price history if we have a product_id and it's not a new product
    lowest_price = None
    lowest_price_date = None
    highest_price = None
    highest_price_date = None
    
    if product_id and notification_type != "new_product":
        price_history = db.get_price_history(product_id)
        lowest_price = price_history['lowest_price']
        lowest_price_date = price_history['lowest_price_date']
        highest_price = price_history['highest_price']
        highest_price_date = price_history['highest_price_date']
    
    # Compose message based on notification_type
    is_new_product = notification_type == "new_product"
    is_price_drop = notification_type == "price_drop"
    is_price_increase = notification_type == "price_increase"
    
    # Compose message header with query name
    message = f"Zoekopdracht: {query_name}\n\n"
    
    # Compose message body
    if is_new_product:
        message += f"Nieuw product gevonden: {label}\nPrijs: €{new_price:.2f}"
        
        # If it's a new product with immediate discount, show that info
        if discount_amount and discount_percentage and discount_amount > 0:
            message += f"\nAanbiedingsprijs! Korting: €{discount_amount:.2f} ({discount_percentage:.1f}%)"
            if old_price and old_price > 0:
                message += f"\nVan €{old_price:.2f} voor €{new_price:.2f}"
    else:
        # It's a price change
        if is_price_drop:
            # Price reduction
            message += f"Prijsverlaging voor {label}"
            message += f"\nVan €{old_price:.2f} naar €{new_price:.2f}"
            
            if discount_amount and discount_percentage and discount_amount > 0:
                message += f"\nJe bespaart: €{discount_amount:.2f} ({discount_percentage:.1f}%)"
        else:
            # Price increase
            message += f"Prijsverhoging voor {label}"
            message += f"\nVan €{old_price:.2f} naar €{new_price:.2f}"
            
            price_increase = new_price - old_price
            percentage_increase = (price_increase / old_price) * 100
            message += f"\nPrijsstijging: €{price_increase:.2f} ({percentage_increase:.1f}%)"
        
        # Add price history to message
        if lowest_price is not None and highest_price is not None:
            message += "\n\nPrijsgeschiedenis:"
            
            # Lowest price
            if lowest_price < new_price:
                message += f"\nLaagste prijs ooit: €{lowest_price:.2f}"
                if lowest_price_date:
                    message += f" op {lowest_price_date.strftime('%d-%m-%Y')}"
            
            # Highest price
            if highest_price > new_price:
                message += f"\nHoogste prijs ooit: €{highest_price:.2f}"
                if highest_price_date:
                    message += f" op {highest_price_date.strftime('%d-%m-%Y')}"
    
    # Log notification in database with error handling
    notification_id = db.save_notification(
        user_id,
        query_id,
        product_id,
        notification_type,
        old_price,
        new_price,
        discount_amount,
        discount_percentage,
        message,
        chat_id
    )
    
    try:
        if image_url:
            # Als er een afbeelding is, stuur alles in één bericht
            await app.bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=message,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(text="Bekijk product", url=product_url)]
                ])
            )
        else:
            # Als er geen afbeelding is, stuur alleen het bericht met de URL
            message += f"\n{product_url}"
            await app.bot.send_message(
                chat_id=chat_id,
                text=message,
                disable_web_page_preview=True
            )
        logger.info(f"Notification sent to {chat_id}: {notification_type} for {label} from query '{query_name}'")
    except Exception as e:
        logger.error(f"Failed to send notification to {chat_id}: {e}")
        # Als het bericht met afbeelding mislukt, probeer een fallback zonder afbeelding
        if image_url:
            try:
                message += f"\n{product_url}"
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Failed to send fallback message to {chat_id}: {e}")
        
    return notification_id