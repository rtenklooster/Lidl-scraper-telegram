import sqlite3
from sqlite3 import Error
import logging
import time
from contextlib import contextmanager
import threading
import random
from queue import Queue, Empty
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Een geavanceerde connection pool implementatie
class ConnectionPool:
    def __init__(self, db_path, max_connections=5, timeout=20):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self.available_connections = []
        self.in_use_connections = set()
        self.lock = threading.RLock()  # Reentrant lock voor thread safety
    
    def get_connection(self):
        """Get a connection from the pool or create a new one if needed."""
        with self.lock:
            if self.available_connections:
                conn = self.available_connections.pop()
                self.in_use_connections.add(conn)
                return conn
            
            if len(self.in_use_connections) < self.max_connections:
                try:
                    conn = sqlite3.connect(self.db_path, timeout=self.timeout)
                    # Configureer SQLite voor betere concurrency
                    conn.execute("PRAGMA busy_timeout = 30000")  # Verhoogd naar 30 seconden
                    conn.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging mode
                    conn.execute("PRAGMA synchronous = NORMAL")  # Betere performance
                    self.in_use_connections.add(conn)
                    return conn
                except Error as e:
                    logger.error(f"Error creating database connection: {e}")
                    return None
        
        # Als we hier zijn, zijn alle connecties in gebruik
        # Wacht en probeer opnieuw met jitter
        for attempt in range(1, 21):  # Max 20 pogingen
            time.sleep(0.1 + (0.1 * attempt) + (random.random() * 0.2))  # Exponential backoff met jitter
            with self.lock:
                if self.available_connections:
                    conn = self.available_connections.pop()
                    self.in_use_connections.add(conn)
                    return conn
        
        logger.error("Connection pool exhausted, could not get a connection")
        raise ConnectionError("Failed to acquire database connection after multiple attempts")
    
    def release_connection(self, conn):
        """Return a connection to the pool."""
        with self.lock:
            if conn in self.in_use_connections:
                self.in_use_connections.remove(conn)
                if len(self.available_connections) < self.max_connections:
                    self.available_connections.append(conn)
                else:
                    conn.close()
    
    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            for conn in self.available_connections:
                conn.close()
            self.available_connections.clear()
            
            # Maak een kopie van in_use_connections om "set changed size during iteration" te voorkomen
            for conn in list(self.in_use_connections):
                try:
                    conn.close()
                except Exception as e:
                    logger.warning(f"Error closing connection: {e}")
            self.in_use_connections.clear()

# Globale connection pool
_connection_pool = None
_pool_lock = threading.Lock()

def initialize_connection_pool(db_path, max_connections=5):
    """Initialize the connection pool."""
    global _connection_pool
    with _pool_lock:
        if _connection_pool is None:
            _connection_pool = ConnectionPool(db_path, max_connections=max_connections)
        return _connection_pool

@contextmanager
def get_connection_context(db_path):
    """Context manager voor het gebruik van database connecties met verbeterde foutafhandeling."""
    global _connection_pool
    if (_connection_pool is None):
        initialize_connection_pool(db_path)
    
    conn = None
    retry_count = 0
    max_retries = 3  # Verlaag retries
    
    while retry_count < max_retries:
        try:
            conn = _connection_pool.get_connection()
            break
        except ConnectionError:
            retry_count += 1
            if retry_count >= max_retries:
                logger.error(f"Failed to get database connection after {max_retries} attempts")
                raise
            backoff = 0.1 * (2 ** retry_count) + (random.random() * 0.5)
            logger.warning(f"Retrying database connection in {backoff:.2f} seconds (attempt {retry_count}/{max_retries})")
            time.sleep(backoff)
    
    if not conn:
        raise ConnectionError("Could not establish database connection")
        
    try:
        yield conn
    except Exception as e:
        logger.exception(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            try:
                conn.commit()
            except Exception as commit_e:
                logger.error(f"Error during commit: {commit_e}")
                conn.rollback()
            _connection_pool.release_connection(conn)

# Logging queue and thread
log_queue = Queue()
log_thread = None

def log_worker(db_path):
    while True:
        try:
            log_entry = log_queue.get(timeout=1)
            if log_entry is None:
                break
            with get_connection_context(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(log_entry['query'], log_entry['params'])
                conn.commit()
        except Empty:
            continue
        except Exception as e:
            logger.exception(f"Error in log worker: {e}")

def start_log_thread(db_path):
    global log_thread
    log_thread = threading.Thread(target=log_worker, args=(db_path,))
    log_thread.start()

def stop_log_thread():
    log_queue.put(None)
    log_thread.join()

def log_query_execution(db_path, query_id, api_url, success, total_results=0, new_products=0, price_changes=0, 
                      error_message=None, response_status=None, execution_time_ms=0):
    log_entry = {
        'query': '''
            INSERT INTO query_executions 
            (query_id, api_url, success, total_results, new_products, price_changes, 
             error_message, response_status, execution_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        'params': (query_id, api_url, success, total_results, new_products, price_changes, 
                   error_message, response_status, execution_time_ms)
    }
    log_queue.put(log_entry)

def log_notification(db_path, user_id, query_id, product_id, notification_type, old_price=None, new_price=None,
                   discount_amount=None, discount_percentage=None, message_text=None, chat_id=None):
    log_entry = {
        'query': '''
            INSERT INTO notifications 
            (user_id, query_id, product_id, notification_type, old_price, new_price, 
             discount_amount, discount_percentage, message_text, chat_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        'params': (user_id, query_id, product_id, notification_type, old_price, new_price, 
                   discount_amount, discount_percentage, message_text, chat_id)
    }
    log_queue.put(log_entry)

def get_connection(db_path):
    """
    Legacy functie voor het verkrijgen van een database connectie.
    Gebruik bij voorkeur get_connection_context voor betere resource handling.
    """
    global _connection_pool
    if _connection_pool is None:
        initialize_connection_pool(db_path)
        
    try:
        conn = _connection_pool.get_connection()
        return conn
    except Error as e:
        logger.error(f"Error connecting to database: {e}")
        return None

def init_db(db_path):
    with get_connection_context(db_path) as conn:
        cursor = conn.cursor()
        
        # Maak de users tabel (indien deze nog niet bestaat)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                username TEXT,
                language TEXT DEFAULT 'nl',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Maak de queries tabel (indien deze nog niet bestaat)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                query_name TEXT,
                query_text TEXT NOT NULL,
                interval_minutes INTEGER DEFAULT 60,
                last_run TIMESTAMP,
                paused BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Maak de products tabel (indien deze nog niet bestaat)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER,
                code TEXT NOT NULL,
                label TEXT NOT NULL,
                price FLOAT,
                image_url TEXT,
                product_url TEXT,
                recommended_price FLOAT,
                discount_amount FLOAT,
                discount_percentage FLOAT,
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (query_id) REFERENCES queries (id)
            )
        ''')
        
        # Maak de price_history tabel (indien deze nog niet bestaat)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                old_price FLOAT,
                new_price FLOAT,
                discount_amount FLOAT,
                discount_percentage FLOAT,
                change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # Maak de query_executions tabel voor het loggen van query uitvoeringen
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS query_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER,
                api_url TEXT NOT NULL,
                execution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success BOOLEAN,
                total_results INTEGER DEFAULT 0,
                new_products INTEGER DEFAULT 0,
                price_changes INTEGER DEFAULT 0,
                error_message TEXT,
                response_status INTEGER,
                execution_time_ms INTEGER,
                FOREIGN KEY (query_id) REFERENCES queries (id)
            )
        ''')
        
        # Maak de notifications tabel voor het loggen van verzonden notificaties
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                query_id INTEGER,
                product_id INTEGER,
                notification_type TEXT NOT NULL,  -- 'new_product', 'price_drop', 'price_increase', etc.
                sent_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                old_price FLOAT,
                new_price FLOAT,
                discount_amount FLOAT,
                discount_percentage FLOAT,
                message_text TEXT,
                chat_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (query_id) REFERENCES queries (id),
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # Maak de notification_stats tabel voor het loggen van geaggregeerde notificatie statistieken
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_execution_id INTEGER,
                user_id INTEGER,
                query_id INTEGER,
                execution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                new_product_count INTEGER DEFAULT 0,
                price_drop_count INTEGER DEFAULT 0,
                price_increase_count INTEGER DEFAULT 0,
                total_notifications INTEGER DEFAULT 0,
                FOREIGN KEY (query_execution_id) REFERENCES query_executions (id),
                FOREIGN KEY (user_id) REFERENCES users (id),
                FOREIGN KEY (query_id) REFERENCES queries (id)
            )
        ''')
        
        # Controleer of de nieuwe kolommen al bestaan, zo niet, voeg ze toe
        cursor.execute("PRAGMA table_info(products)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'discount_amount' not in columns:
            cursor.execute('ALTER TABLE products ADD COLUMN discount_amount FLOAT')
        
        if 'discount_percentage' not in columns:
            cursor.execute('ALTER TABLE products ADD COLUMN discount_percentage FLOAT')
        
        cursor.execute("PRAGMA table_info(price_history)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'discount_amount' not in columns:
            cursor.execute('ALTER TABLE price_history ADD COLUMN discount_amount FLOAT')
        
        if 'discount_percentage' not in columns:
            cursor.execute('ALTER TABLE price_history ADD COLUMN discount_percentage FLOAT')
        
        logger.info(f"Database {db_path} initialized successfully.")

def execute_query(db_path, query, params=(), max_retries=3):
    """Execute a query with enhanced retry logic for database locks."""
    for retry in range(max_retries):
        try:
            with get_connection_context(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                return True
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < max_retries - 1:
                backoff = 0.2 * (2 ** retry) + (random.random() * 0.2)
                logger.warning(f"Database locked during query execution, retrying in {backoff:.2f}s ({retry+1}/{max_retries})")
                time.sleep(backoff)
            else:
                logger.error(f"Failed to execute query after {retry+1} attempts: {e}")
                raise
        except Exception as e:
            logger.exception(f"Error executing query: {e}")
            raise
    
    return False

def execute_select(db_path, query, params=(), max_retries=3):
    """Execute a SELECT query with enhanced retry logic for database locks."""
    for retry in range(max_retries):
        try:
            with get_connection_context(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                results = cursor.fetchall()
                return results
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < max_retries - 1:
                backoff = 0.2 * (2 ** retry) + (random.random() * 0.2)
                logger.warning(f"Database locked during select, retrying in {backoff:.2f}s ({retry+1}/{max_retries})")
                time.sleep(backoff)
            else:
                logger.error(f"Failed to execute select after {retry+1} attempts: {e}")
                raise
        except Exception as e:
            logger.exception(f"Error executing select: {e}")
            raise
    
    return []

def log_notification_standalone(db_path, user_id, query_id, product_id, notification_type, old_price=None, new_price=None,
                             discount_amount=None, discount_percentage=None, message_text=None, chat_id=None):
    """
    Zelfstandige functie om een notificatie te loggen in een aparte transactie.
    Dit voorkomt blokkering van de hoofdtransactie als er een database lock optreedt.
    """
    max_retries = 15  # Zeer hoog aantal retries voor deze kritieke operatie
    
    for retry in range(max_retries):
        try:
            # Gebruik een geheel nieuwe database verbinding voor deze operatie
            # Dit voorkomt lock contentie met andere connecties
            conn = sqlite3.connect(db_path, timeout=30.0)
            conn.execute("PRAGMA busy_timeout = 30000")  # 30 seconden timeout
            
            try:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO notifications 
                    (user_id, query_id, product_id, notification_type, old_price, new_price, 
                    discount_amount, discount_percentage, message_text, chat_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, query_id, product_id, notification_type, old_price, new_price, 
                    discount_amount, discount_percentage, message_text, chat_id))
                
                conn.commit()
                result = cursor.lastrowid
                conn.close()
                return result
            except Exception as inner_e:
                conn.rollback()
                conn.close()
                raise inner_e
                
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < max_retries - 1:
                # Nog agressievere backoff strategie
                backoff = 0.5 * (2 ** retry) + (random.random() * 0.5)
                logger.warning(f"Database locked in standalone notification logging, retry {retry+1}/{max_retries} in {backoff:.2f}s")
                time.sleep(backoff)
            else:
                logger.error(f"Failed to log notification in standalone mode after {retry+1} attempts: {e}")
                return None
        except Exception as e:
            logger.exception(f"Error in standalone notification logging: {e}")
            return None
    
    logger.error("Maximum retries exceeded for standalone notification logging")
    return None

def update_notification_stats(conn, query_execution_id, user_id, query_id, new_product_count=0, 
                            price_drop_count=0, price_increase_count=0):
    """
    Update de geaggregeerde notificatie statistieken voor een query uitvoering met verbeterde foutafhandeling.
    """
    cursor = conn.cursor()
    total_notifications = new_product_count + price_drop_count + price_increase_count
    max_retries = 10  # Verhoogd aantal retries
    
    for retry in range(max_retries):
        try:
            cursor.execute('''
                INSERT INTO notification_stats 
                (query_execution_id, user_id, query_id, new_product_count, price_drop_count, 
                 price_increase_count, total_notifications)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (query_execution_id, user_id, query_id, new_product_count, price_drop_count, 
                 price_increase_count, total_notifications))
            return cursor.lastrowid
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < max_retries - 1:
                backoff = 0.3 * (2 ** retry) + (random.random() * 0.4)
                logger.warning(f"Database locked while updating notification stats, retry {retry+1}/{max_retries} in {backoff:.2f}s")
                time.sleep(backoff)
            else:
                logger.error(f"Failed to update notification stats after {retry+1} attempts: {e}")
                raise
        except Exception as e:
            logger.exception(f"Error updating notification stats: {e}")
            raise
    
    return None

def log_query_execution(conn, query_id, api_url, success, total_results=0, new_products=0, price_changes=0, 
                      error_message=None, response_status=None, execution_time_ms=0):
    """
    Log een query uitvoering in de database met verbeterde error handling.
    """
    cursor = conn.cursor()
    max_retries = 5
    for retry in range(max_retries):
        try:
            cursor.execute('''
                INSERT INTO query_executions 
                (query_id, api_url, success, total_results, new_products, price_changes, 
                 error_message, response_status, execution_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (query_id, api_url, success, total_results, new_products, price_changes, 
                 error_message, response_status, execution_time_ms))
            return cursor.lastrowid
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry < max_retries - 1:
                backoff = 0.2 * (2 ** retry) + (random.random() * 0.2)
                logger.warning(f"Database locked during log_query_execution, retrying in {backoff:.2f}s ({retry+1}/{max_retries})")
                time.sleep(backoff)
            else:
                logger.error(f"Failed to log query execution after {retry+1} attempts: {e}")
                raise
        except Exception as e:
            logger.exception(f"Error logging query execution: {e}")
            raise
    
    return None

# Start de log thread bij het initialiseren van de database
start_log_thread('lidl_scraper.db')

# Nieuwe centraal database service class voor alle database operaties
class DatabaseService:
    """
    Centrale service voor alle database operaties.
    Dit elimineert directe database toegang vanuit andere modules.
    """
    def __init__(self, db_path):
        """
        Initialiseer de database service.
        
        Args:
            db_path: Naam van het database bestand
        """
        self.db_path = db_path
    
    def get_user_for_query(self, query_id: int) -> Tuple[Optional[int], Optional[str]]:
        """
        Haal gebruiker informatie op voor een query.
        
        Args:
            query_id: ID van de query
            
        Returns:
            Tuple met (user_id, chat_id) of (None, None) als niet gevonden
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT q.user_id, u.chat_id 
                    FROM queries q 
                    JOIN users u ON q.user_id = u.id 
                    WHERE q.id = ?
                """, (query_id,))
                
                user_row = cursor.fetchone()
                
                if not user_row:
                    return None, None
                    
                return user_row[0], user_row[1]
        except Exception as e:
            logger.exception(f"Error getting user for query: {e}")
            return None, None
    
    def find_product_id_by_label(self, query_id: int, label: str) -> Optional[int]:
        """
        Zoek een product ID op basis van label en query ID.
        
        Args:
            query_id: ID van de query
            label: Naam van het product
            
        Returns:
            Product ID of None als niet gevonden
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM products WHERE query_id = ? AND label = ? ORDER BY id DESC LIMIT 1", 
                             (query_id, label))
                product_row = cursor.fetchone()
                if product_row:
                    return product_row[0]
                return None
        except Exception as e:
            logger.exception(f"Error finding product ID: {e}")
            return None
    
    def get_price_history(self, product_id: int) -> Dict[str, Any]:
        """
        Haal prijsgeschiedenis op voor een product.
        
        Args:
            product_id: ID van het product
            
        Returns:
            Dictionary met prijsgeschiedenis informatie
        """
        result = {
            'lowest_price': None,
            'lowest_price_date': None,
            'highest_price': None,
            'highest_price_date': None
        }
        
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Lowest recorded price
                cursor.execute("""
                    SELECT MIN(new_price), change_date FROM price_history 
                    WHERE product_id = ? AND new_price > 0
                    GROUP BY product_id
                """, (product_id,))
                lowest_row = cursor.fetchone()
                
                if lowest_row:
                    result['lowest_price'] = lowest_row[0]
                    result['lowest_price_date'] = datetime.fromisoformat(lowest_row[1]) if lowest_row[1] else None
                
                # Highest recorded price
                cursor.execute("""
                    SELECT MAX(new_price), change_date FROM price_history 
                    WHERE product_id = ?
                    GROUP BY product_id
                """, (product_id,))
                highest_row = cursor.fetchone()
                
                if highest_row:
                    result['highest_price'] = highest_row[0]
                    result['highest_price_date'] = datetime.fromisoformat(highest_row[1]) if highest_row[1] else None
                    
                return result
        except Exception as e:
            logger.exception(f"Error getting price history: {e}")
            return result
    
    def save_notification(self, user_id: int, query_id: int, product_id: int, notification_type: str,
                         old_price: float, new_price: float, discount_amount: float, discount_percentage: float,
                         message: str, chat_id: str) -> Optional[int]:
        """
        Sla een notificatie op in de database en update statistieken.
        
        Args:
            Alle velden voor de notificatie
            
        Returns:
            ID van de aangemaakte notificatie of None bij fout
        """
        notification_id = None
        try:
            with get_connection_context(self.db_path) as conn:
                # Log de notificatie
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO notifications 
                    (user_id, query_id, product_id, notification_type, old_price, new_price, 
                    discount_amount, discount_percentage, message_text, chat_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, query_id, product_id, notification_type, old_price, new_price, 
                    discount_amount, discount_percentage, message, chat_id))
                
                notification_id = cursor.lastrowid
                
                # Update statistieken in dezelfde transactie
                is_new_product = notification_type == "new_product"
                is_price_drop = notification_type == "price_drop"
                is_price_increase = notification_type == "price_increase"
                
                # Get current query execution to update stats
                cursor.execute("""
                    SELECT id FROM query_executions 
                    WHERE query_id = ? 
                    ORDER BY execution_date DESC 
                    LIMIT 1
                """, (query_id,))
                
                execution_row = cursor.fetchone()
                
                if execution_row:
                    query_execution_id = execution_row[0]
                    
                    # Check if we already have stats for this execution
                    cursor.execute("""
                        SELECT id, new_product_count, price_drop_count, price_increase_count 
                        FROM notification_stats 
                        WHERE query_execution_id = ? AND user_id = ?
                    """, (query_execution_id, user_id))
                    
                    stats_row = cursor.fetchone()
                    
                    if stats_row:
                        # Update existing stats
                        stats_id = stats_row[0]
                        new_count = stats_row[1] + (1 if is_new_product else 0)
                        drop_count = stats_row[2] + (1 if is_price_drop else 0)
                        increase_count = stats_row[3] + (1 if is_price_increase else 0)
                        total_count = new_count + drop_count + increase_count
                        
                        cursor.execute("""
                            UPDATE notification_stats 
                            SET new_product_count = ?, price_drop_count = ?, price_increase_count = ?, total_notifications = ?
                            WHERE id = ?
                        """, (new_count, drop_count, increase_count, total_count, stats_id))
                    else:
                        # Create new stats
                        cursor.execute('''
                            INSERT INTO notification_stats 
                            (query_execution_id, user_id, query_id, new_product_count, price_drop_count, 
                            price_increase_count, total_notifications)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (query_execution_id, user_id, query_id, 
                            1 if is_new_product else 0,
                            1 if is_price_drop else 0,
                            1 if is_price_increase else 0,
                            1))
            
            return notification_id
        except Exception as e:
            logger.exception(f"Error saving notification: {e}")
            return None
    
    def get_active_queries(self) -> List[Tuple]:
        """
        Haal alle actieve queries op.
        
        Returns:
            Lijst met (id, query_text, interval_minutes, last_run) tuples
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, query_text, interval_minutes, last_run FROM queries WHERE paused = 0")
                return cursor.fetchall()
        except Exception as e:
            logger.exception(f"Error getting active queries: {e}")
            return []
    
    def update_query_last_run(self, query_id: int, timestamp: str) -> bool:
        """
        Update de last_run timestamp van een query.
        
        Args:
            query_id: ID van de query
            timestamp: ISO timestamp string
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE queries SET last_run = ? WHERE id = ?", (timestamp, query_id))
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error updating query last_run: {e}")
            return False
    
    def process_products(self, query_id: int, products: list) -> Tuple[int, int, List[Dict]]:
        """
        Verwerk producten uit een scraper en sla ze op in de database.
        
        Args:
            query_id: ID van de query
            products: Lijst met product objecten van de scraper
            
        Returns:
            Tuple met (nieuwe_products_count, price_changes_count, notifications)
        """
        new_products_count = 0
        price_changes_count = 0
        notifications = []
        
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                
                for product in products:
                    # Check if product already exists
                    cursor.execute("SELECT id, price FROM products WHERE query_id = ? AND code = ?", (query_id, product.id))
                    existing_product = cursor.fetchone()
                    
                    if not existing_product:
                        # New product, add it
                        cursor.execute(
                            """
                            INSERT INTO products (query_id, code, label, price, image_url, product_url, recommended_price, 
                            discount_amount, discount_percentage)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (query_id, product.id, product.name, product.price, product.image_url, product.product_url, 
                             product.recommended_price, product.discount_amount, product.discount_percentage),
                        )
                        
                        product_row_id = cursor.lastrowid
                        
                        logger.info(f"New product found for query {query_id}: {product.name}")
                        new_products_count += 1
                        
                        # Add notification to list
                        notifications.append({
                            'query_id': query_id,
                            'product_id': product_row_id,
                            'label': product.name,
                            'new_price': product.price,
                            'old_price': product.old_price,
                            'product_url': product.product_url,
                            'image_url': product.image_url,
                            'notification_type': "new_product",
                            'discount_amount': product.discount_amount,
                            'discount_percentage': product.discount_percentage
                        })
                    else:
                        # Check if price has changed
                        existing_id = existing_product[0]
                        existing_price = existing_product[1]
                        
                        if product.price != existing_price:
                            # Determine type of price change
                            notification_type = "price_drop" if product.price < existing_price else "price_increase"
                            
                            # Update product price and discount information
                            cursor.execute("""
                                UPDATE products 
                                SET price = ?, recommended_price = ?, discount_amount = ?, discount_percentage = ? 
                                WHERE id = ?
                            """, (product.price, product.recommended_price, product.discount_amount, 
                                 product.discount_percentage, existing_id))
                            
                            # Log the price change in price_history table
                            cursor.execute(
                                """
                                INSERT INTO price_history (product_id, old_price, new_price, discount_amount, discount_percentage, change_date)
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (existing_id, existing_price, product.price, 
                                 product.discount_amount, product.discount_percentage, datetime.now()),
                            )
                            
                            logger.info(f"Price updated for product {query_id}: {product.name} from {existing_price} to {product.price}")
                            price_changes_count += 1
                            
                            # Add notification to list
                            notifications.append({
                                'query_id': query_id,
                                'product_id': existing_id,
                                'label': product.name,
                                'new_price': product.price,
                                'old_price': existing_price,
                                'product_url': product.product_url,
                                'image_url': product.image_url,
                                'notification_type': notification_type,
                                'discount_amount': product.discount_amount,
                                'discount_percentage': product.discount_percentage
                            })
                
                conn.commit()
                return (new_products_count, price_changes_count, notifications)
        except Exception as e:
            logger.exception(f"Error processing products for query {query_id}: {e}")
            return (0, 0, [])
    
    def log_query_execution_result(self, query_id: int, api_url: str, success: bool, 
                                 total_products: int, new_products: int, price_changes: int,
                                 error_message: str = None, response_status: int = None, 
                                 execution_time_ms: int = 0) -> Optional[int]:
        """
        Log het resultaat van een query uitvoering.
        
        Args:
            Alle velden voor de query execution log
            
        Returns:
            ID van de aangemaakte log entry of None bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO query_executions 
                    (query_id, api_url, success, total_results, new_products, price_changes, 
                     error_message, response_status, execution_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (query_id, api_url, success, total_products, new_products, price_changes, 
                     error_message, response_status, execution_time_ms))
                return cursor.lastrowid
        except Exception as e:
            logger.exception(f"Error logging query execution: {e}")
            return None
    
    def add_query_for_chat_id(self, chat_id: str, query_name: str, query_text: str) -> Tuple[bool, str]:
        """
        Voegt een nieuwe query toe voor een gegeven chat ID.
        
        Args:
            chat_id: De chat ID van de gebruiker
            query_name: De naam van de query
            query_text: De query tekst (API URL)
            
        Returns:
            tuple: (success, message)
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                # Get user_id for the foreign key
                cursor.execute("SELECT id FROM users WHERE chat_id=?", (chat_id,))
                user = cursor.fetchone()
                
                if not user:
                    return False, "Er ging iets mis. Probeer opnieuw met /start."

                user_id = user[0]
                cursor.execute(
                    "INSERT INTO queries (user_id, query_name, query_text) VALUES (?,?,?)",
                    (user_id, query_name, query_text)
                )
                conn.commit()
                return True, f"Zoekopdracht '{query_name}' is toegevoegd."
        except Exception as e:
            logger.exception(f"Error adding query for chat_id {chat_id}: {e}")
            return False, "Er ging iets mis bij het opslaan van de query."
    
    # Bot Commands gerelateerde methoden
    
    def get_user_by_chat_id(self, chat_id: str) -> Optional[Tuple]:
        """
        Zoek een gebruiker op basis van chat ID.
        
        Args:
            chat_id: De chat ID van de gebruiker
            
        Returns:
            Gebruiker tuple of None als niet gevonden
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE chat_id=?", (chat_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.exception(f"Error finding user by chat_id {chat_id}: {e}")
            return None
    
    def register_new_user(self, chat_id: str, username: str, language: str = "nl") -> bool:
        """
        Registreer een nieuwe gebruiker.
        
        Args:
            chat_id: De chat ID van de gebruiker
            username: De gebruikersnaam
            language: De taal van de gebruiker (standaard 'nl')
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (chat_id, username, language) VALUES (?, ?, ?)", 
                    (chat_id, username, language)
                )
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error registering new user {chat_id}: {e}")
            return False
    
    def update_user_language(self, chat_id: str, language: str) -> bool:
        """
        Update de taal van een gebruiker.
        
        Args:
            chat_id: De chat ID van de gebruiker
            language: De nieuwe taal code (nl/en)
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET language = ? WHERE chat_id = ?", (language, chat_id))
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error updating language for user {chat_id}: {e}")
            return False
    
    def get_queries_for_chat_id(self, chat_id: str) -> List[Tuple]:
        """
        Haal alle queries op voor een chat ID.
        
        Args:
            chat_id: De chat ID van de gebruiker
            
        Returns:
            Lijst met query tuples (id, query_name, interval_minutes, paused)
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT q.id, q.query_name, q.interval_minutes, q.paused
                    FROM queries q
                    JOIN users u ON q.user_id = u.id
                    WHERE u.chat_id = ?
                """, (chat_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.exception(f"Error getting queries for chat_id {chat_id}: {e}")
            return []
    
    def get_active_queries_for_chat_id(self, chat_id: str) -> List[Tuple]:
        """
        Haal alle actieve (niet gepauzeerde) queries op voor een chat ID.
        
        Args:
            chat_id: De chat ID van de gebruiker
            
        Returns:
            Lijst met query tuples (id, query_name, query_text)
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT q.id, q.query_name, q.query_text
                    FROM queries q
                    JOIN users u ON q.user_id = u.id
                    WHERE u.chat_id = ? AND q.paused = 0
                """, (chat_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.exception(f"Error getting active queries for chat_id {chat_id}: {e}")
            return []
    
    def get_paused_queries_for_chat_id(self, chat_id: str) -> List[Tuple]:
        """
        Haal alle gepauzeerde queries op voor een chat ID.
        
        Args:
            chat_id: De chat ID van de gebruiker
            
        Returns:
            Lijst met query tuples (id, query_name, query_text)
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT q.id, q.query_name, q.query_text
                    FROM queries q
                    JOIN users u ON q.user_id = u.id
                    WHERE u.chat_id = ? AND q.paused = 1
                """, (chat_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.exception(f"Error getting paused queries for chat_id {chat_id}: {e}")
            return []
    
    def get_query_name(self, query_id: int) -> Optional[str]:
        """
        Haal de naam op van een query.
        
        Args:
            query_id: De ID van de query
            
        Returns:
            De naam van de query of None als niet gevonden
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT query_name FROM queries WHERE id = ?", (query_id,))
                row = cursor.fetchone()
                if row:
                    return row[0]
                return None
        except Exception as e:
            logger.exception(f"Error getting query name for ID {query_id}: {e}")
            return None
    
    def pause_query(self, query_id: int) -> bool:
        """
        Pauzeer een query.
        
        Args:
            query_id: De ID van de query
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE queries SET paused = 1 WHERE id = ?", (query_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error pausing query {query_id}: {e}")
            return False
    
    def resume_query(self, query_id: int) -> bool:
        """
        Hervat een query.
        
        Args:
            query_id: De ID van de query
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE queries SET paused = 0 WHERE id = ?", (query_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error resuming query {query_id}: {e}")
            return False
    
    def delete_query(self, query_id: int) -> bool:
        """
        Verwijder een query.
        
        Args:
            query_id: De ID van de query
            
        Returns:
            True als succesvol, False bij fout
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM queries WHERE id = ?", (query_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.exception(f"Error deleting query {query_id}: {e}")
            return False
    
    def is_initial_query_execution(self, query_id: int) -> bool:
        """
        Controleer of dit de eerste uitvoering van de query is.
        
        Args:
            query_id: De ID van de query
            
        Returns:
            True als dit de eerste uitvoering is, anders False
        """
        try:
            with get_connection_context(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM query_executions WHERE query_id = ?", (query_id,))
                count = cursor.fetchone()[0]
                return count == 0
        except Exception as e:
            logger.exception(f"Error checking initial query execution for query ID {query_id}: {e}")
            return False

# Creëer een globale database service instantie voor gebruik in de hele applicatie
db_service = DatabaseService('lidl_scraper.db')