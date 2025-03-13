"""
Query Processing Module
Handles all query execution logic, product processing, and database interactions for query results.
"""
import logging
import time
from datetime import datetime, timedelta
import importlib
import re
import database
from config import DATABASE_NAME
from scrapers.lidl import LidlScraper

logger = logging.getLogger(__name__)

def get_scraper_for_url(url: str):
    """
    Determine which scraper to use based on the URL.
    This function can be extended to support multiple scrapers.
    
    Args:
        url: The URL to determine scraper for
        
    Returns:
        An instance of the appropriate scraper
    """
    # Currently only supports Lidl, but can be extended
    if "lidl" in url:
        return LidlScraper()
    else:
        # Default to Lidl scraper for now
        # In the future, this could be more sophisticated
        # or raise an error if no matching scraper is found
        return LidlScraper()

async def execute_query(query_id: int, query_text: str):
    """
    Execute a query and process its results.
    Uses the appropriate scraper's paginated query functionality.
    
    Args:
        query_id: The database ID of the query
        query_text: The query text (URL or API endpoint)
    
    Returns:
        tuple: (success, notifications)
    """
    try:
        # Track execution time
        execution_start_time = time.time()
        
        # Determine which scraper to use based on the URL
        scraper = get_scraper_for_url(query_text)
        
        # Convert URL to API URL for logging
        api_url = scraper.convert_url_to_api_url(query_text)
        
        # Execute paginated query using the scraper implementation
        # This encapsulates all the site-specific pagination logic
        all_products, success, total_products, error_message, response_status = scraper.execute_paginated_query(query_text)
        
        # Process products using database service
        db = database.db_service
        
        # Process products
        total_new_products = 0
        total_price_changes = 0
        all_notifications = []
        
        if all_products:
            new_products, price_changes, notifications = db.process_products(query_id, all_products)
            total_new_products = new_products
            total_price_changes = price_changes
            all_notifications = notifications
        
        # Calculate total execution time
        execution_time_ms = int((time.time() - execution_start_time) * 1000)
        
        # Log the query execution using database service
        db.log_query_execution_result(
            query_id,
            api_url,
            success,
            total_products,
            total_new_products,
            total_price_changes,
            error_message,
            response_status,
            execution_time_ms
        )
        
        # Return result and notifications for sending
        logger.info(f"Query {query_id} completed, found {total_products} total products. New: {total_new_products}, Price changes: {total_price_changes}")
        return success, all_notifications
        
    except Exception as e:
        logger.exception(f"Error executing query {query_id}: {e}")
        
        # Log the failed query
        execution_time_ms = int((time.time() - execution_start_time) * 1000) if 'execution_start_time' in locals() else 0
        api_url = scraper.convert_url_to_api_url(query_text) if 'scraper' in locals() else query_text
        
        # Use database service to log the error
        db = database.db_service
        db.log_query_execution_result(
            query_id,
            api_url,
            False,
            0,
            0,
            0,
            str(e),
            None,
            execution_time_ms
        )
        
        return False, []

def convert_url_to_api(url):
    """
    Convert a regular URL to API query format.
    Delegates to the appropriate scraper for implementation.
    
    Args:
        url: The URL to convert
    
    Returns:
        str: The converted API URL
    """
    scraper = get_scraper_for_url(url)
    return scraper.convert_url_to_api_url(url)

# Alias for backwards compatibility
convert_lidl_url_to_api = convert_url_to_api

async def check_queries(app):
    """
    Periodically check for queries that need to be executed.
    
    Args:
        app: The Telegram application instance for sending notifications
    """
    from modules.notification import notify_user
    logger.info("Checking queries for execution...")
    
    # Gebruik database service voor database operaties
    db = database.db_service
    
    # Haal actieve queries op
    queries = db.get_active_queries()

    for query_id, query_text, interval_minutes, last_run_str in queries:
        if last_run_str:
            last_run = datetime.fromisoformat(last_run_str)
        else:
            last_run = None

        now = datetime.now()
        if last_run is None or now - last_run >= timedelta(minutes=interval_minutes):
            logger.info(f"Executing query {query_id}...")
            
            # Execute the query (geen database verbinding meer nodig)
            success, notifications = await execute_query(query_id, query_text)
            
            # Update last_run only if query executed successfully
            if success:
                db.update_query_last_run(query_id, now.isoformat())
                logger.info(f"Query {query_id} executed successfully, last_run updated")
                
                # Process notifications
                for notification in notifications:
                    await notify_user(
                        app=app,
                        query_id=notification['query_id'],
                        product_id=notification['product_id'],
                        label=notification['label'],
                        new_price=notification['new_price'],
                        old_price=notification['old_price'],
                        product_url=notification['product_url'],
                        image_url=notification['image_url'],
                        notification_type=notification['notification_type'],
                        discount_amount=notification['discount_amount'],
                        discount_percentage=notification['discount_percentage']
                    )
            else:
                logger.warning(f"Query {query_id} failed, last_run not updated")
        else:
            logger.info(f"Skipping query {query_id}, last run was {last_run}")

    logger.info("Query check complete.")