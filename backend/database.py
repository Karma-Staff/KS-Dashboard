"""
Database module for the Financial Dashboard application.
Handles SQLite database operations for dashboards and conversations.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from passlib.context import CryptContext

# Password hashing configuration
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Database file path support for Render Persistent Disks
DATA_DIR_PATH = os.getenv("PERSISTENT_DATA_DIR")
if DATA_DIR_PATH and os.path.exists(os.path.dirname(DATA_DIR_PATH)):
    # Ensure the directory exists
    if not os.path.exists(DATA_DIR_PATH):
        try:
            os.makedirs(DATA_DIR_PATH, exist_ok=True)
        except:
            pass
    DB_PATH = os.path.join(DATA_DIR_PATH, "dashboard.db")
else:
    # Default to local directory for development
    base_path = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(base_path, "dashboard.db")

print(f"DATABASE PATH: {DB_PATH}")

def get_connection():
    """Get a database connection with row factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize the database with required tables."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create dashboards table - with user_id
    # Note: SQLite doesn't support adding FK constraints to existing tables easily, 
    # but since this is an IF NOT EXISTS, we'll define it correctly.
    # If it already exists, we might need a migration if we were in production,
    # but for this dev setup we'll just ensure the column exists.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT DEFAULT 'Untitled',
            data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # Check if user_id column exists (simple migration)
    cursor.execute("PRAGMA table_info(dashboards)")
    columns = [row['name'] for row in cursor.fetchall()]
    if 'user_id' not in columns:
        cursor.execute("ALTER TABLE dashboards ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
    
    # Initialize default users (needed for the update below)
    init_default_users()
    
    # Ensure existing dashboards have an owner (admin = ID 1)
    cursor.execute("UPDATE dashboards SET user_id = 1 WHERE user_id IS NULL")
    
    # Create conversations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id INTEGER NOT NULL,
            user_message TEXT NOT NULL,
            ai_response TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dashboard_id) REFERENCES dashboards(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()


# ============= Dashboard Operations =============

def create_dashboard(name: str, data: Dict[str, Any], user_id: int) -> int:
    """Create a new dashboard and return its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO dashboards (name, data, user_id) VALUES (?, ?, ?)",
        (name, json.dumps(data), user_id)
    )
    
    dashboard_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return dashboard_id


def get_all_dashboards(user_id: int, is_admin: bool = False) -> List[Dict[str, Any]]:
    """Get all dashboards for a user (Admin sees all)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if is_admin:
        cursor.execute("""
            SELECT d.id, d.name, d.created_at, d.updated_at, u.username as owner
            FROM dashboards d
            JOIN users u ON d.user_id = u.id
            ORDER BY d.updated_at DESC
        """)
    else:
        cursor.execute("""
            SELECT id, name, created_at, updated_at 
            FROM dashboards 
            WHERE user_id = ?
            ORDER BY updated_at DESC
        """, (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_dashboard(dashboard_id: int) -> Optional[Dict[str, Any]]:
    """Get a single dashboard with its full data."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM dashboards WHERE id = ?", (dashboard_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        result = dict(row)
        result['data'] = json.loads(result['data'])
        return result
    return None


def update_dashboard_name(dashboard_id: int, name: str) -> bool:
    """Update a dashboard's name."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE dashboards SET name = ?, updated_at = ? WHERE id = ?",
        (name, datetime.now().isoformat(), dashboard_id)
    )
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


def delete_dashboard(dashboard_id: int) -> bool:
    """Delete a dashboard and its conversations."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM dashboards WHERE id = ?", (dashboard_id,))
    
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return success


# ============= User Management Operations =============

def get_all_users() -> List[Dict[str, Any]]:
    """Retrieve all users in the system."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, is_admin, created_at FROM users ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_user(user_id: int) -> bool:
    """Delete a user and all their dashboards."""
    conn = get_connection()
    cursor = conn.cursor()
    # Cascading delete is handled by foreign key in database schema
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success


def get_next_untitled_name() -> str:
    """Get the next 'Untitled' name (Untitled, Untitled-1, Untitled-2, etc.)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM dashboards WHERE name LIKE 'Untitled%'")
    existing_names = [row['name'] for row in cursor.fetchall()]
    conn.close()
    
    if 'Untitled' not in existing_names:
        return 'Untitled'
    
    counter = 1
    while f'Untitled-{counter}' in existing_names:
        counter += 1
    
    return f'Untitled-{counter}'


# ============= Conversation Operations =============

def save_conversation(dashboard_id: int, user_message: str, ai_response: str) -> int:
    """Save a conversation message pair and return its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO conversations (dashboard_id, user_message, ai_response) VALUES (?, ?, ?)",
        (dashboard_id, user_message, ai_response)
    )
    
    conversation_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return conversation_id


def get_conversations(dashboard_id: int) -> List[Dict[str, Any]]:
    """Get all conversations for a dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM conversations WHERE dashboard_id = ? ORDER BY created_at ASC",
        (dashboard_id,)
    )
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def clear_conversations(dashboard_id: int) -> bool:
    """Clear all conversations for a dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM conversations WHERE dashboard_id = ?", (dashboard_id,))
    
    conn.commit()
    conn.close()
    
    return True


# ============= User Operations =============

def get_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_user(username: str, password: str, full_name: str, is_admin: bool = False) -> int:
    """Create a new user."""
    conn = get_connection()
    cursor = conn.cursor()
    
    password_hash = get_hash(password)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, full_name, is_admin) VALUES (?, ?, ?, ?)",
            (username, password_hash, full_name, 1 if is_admin else 0)
        )
        user_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        user_id = -1
    finally:
        conn.close()
        
    return user_id


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Get a user by username."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def init_default_users():
    """Create default admin and user accounts if they don't exist."""
    if not get_user_by_username("admin"):
        create_user("admin", "password123", "System Administrator", is_admin=True)


# Initialize database on module import
init_db()
