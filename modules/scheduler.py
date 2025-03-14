"""
Scheduler Module
Handles scheduling and executing periodic tasks.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from config import TOKEN
from modules.query_processor import check_queries

logger = logging.getLogger(__name__)

class TaskScheduler:
    """
    Manages scheduled tasks like checking for queries to run.
    """
    def __init__(self, app):
        """
        Initialize the scheduler with a reference to the Telegram application.
        
        Args:
            app: The Telegram application instance
        """
        self.app = app
        self.is_running = False
        self.scheduler_task = None
        # We'll create the event in the start method to ensure it's created in the correct loop
        self._stopped = None
        
    async def start(self):
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return
        
        # Create the Event in the current event loop
        self._stopped = asyncio.Event()
        self.is_running = True
        self._stopped.clear()
        
        # Create the task in the current event loop
        self.scheduler_task = asyncio.create_task(self._run_scheduler())
        logger.info("Task scheduler started")
        
    async def stop(self):
        """Stop the scheduler."""
        if not self.is_running:
            logger.warning("Scheduler is not running")
            return
            
        self.is_running = False
        
        # Only set the event if it exists and was created in this loop
        if self._stopped is not None:
            try:
                self._stopped.set()
            except RuntimeError as e:
                logger.warning(f"Could not set the stop event: {e}")
        
        if self.scheduler_task:
            try:
                self.scheduler_task.cancel()
                await asyncio.wait_for(asyncio.shield(self.scheduler_task), timeout=10)
            except asyncio.TimeoutError:
                logger.error("Failed to cancel scheduler task within timeout")
            except asyncio.CancelledError:
                logger.info("Scheduler task cancelled successfully")
            except Exception as e:
                logger.error(f"Error during scheduler task cancellation: {e}")
            finally:
                self.scheduler_task = None
                
        logger.info("Task scheduler stopped")
        
    async def _run_scheduler(self):
        """Run the scheduler loop to check for and execute queries."""
        try:
            while self.is_running:
                try:
                    await check_queries(self.app)
                except Exception as e:
                    logger.exception(f"Error in check_queries: {e}")
                    
                # Sleep but be responsive to cancellation
                try:
                    # Use a simple sleep rather than waiting on the event
                    for _ in range(6):  # Check every 60 seconds (10 seconds * 6)
                        if not self.is_running:
                            break
                        await asyncio.sleep(10)
                except asyncio.CancelledError:
                    logger.info("Sleep was cancelled")
                    break
                    
                if not self.is_running:
                    break
        except asyncio.CancelledError:
            logger.info("Scheduler task was cancelled")
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in scheduler loop: {e}")
            self.is_running = False
            
        logger.info("Scheduler loop exited")
        
async def update_intervals():
    """
    Update query intervals based on activity and results.
    This could be used to dynamically adjust how often queries are run
    based on how often products are changing.
    """
    logger.info("Updating query intervals")
    
    with database.get_connection_context(args.db_path) as conn:
        cursor = conn.cursor()
        
        # Get all active queries
        cursor.execute("""
            SELECT q.id, q.interval_minutes, MAX(qe.execution_date) as last_exec,
                   COUNT(p.id) as product_count, 
                   SUM(CASE WHEN ph.id IS NOT NULL THEN 1 ELSE 0 END) as price_changes
            FROM queries q
            LEFT JOIN query_executions qe ON q.id = qe.query_id
            LEFT JOIN products p ON q.id = p.query_id
            LEFT JOIN price_history ph ON p.id = ph.product_id
            WHERE q.paused = 0
            GROUP BY q.id
        """)
        
        query_stats = cursor.fetchall()
        
        for query_id, interval, last_exec, product_count, price_changes in query_stats:
            # Simple algorithm: if no price changes in last week, increase interval
            if price_changes == 0 and product_count > 0:
                # Increase interval (less frequent checks) but cap at 12 hours
                new_interval = min(interval * 1.5, 720)
                cursor.execute("UPDATE queries SET interval_minutes = ? WHERE id = ?", 
                               (new_interval, query_id))
                logger.info(f"Increasing interval for query {query_id} to {new_interval} minutes")
            elif price_changes > 5:
                # Frequent price changes, decrease interval (more frequent checks) but minimum 15 minutes
                new_interval = max(interval * 0.75, 15)
                cursor.execute("UPDATE queries SET interval_minutes = ? WHERE id = ?", 
                               (new_interval, query_id))
                logger.info(f"Decreasing interval for query {query_id} to {new_interval} minutes")
                
        conn.commit()