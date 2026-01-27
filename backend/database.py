"""
Database module for the Financial Dashboard application.
Handles SQLite database operations for dashboards and conversations.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

# Database file path (same directory as this script)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.db")


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
    
    # Create dashboards table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT 'Untitled',
            data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
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

def create_dashboard(name: str, data: Dict[str, Any]) -> int:
    """Create a new dashboard and return its ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO dashboards (name, data) VALUES (?, ?)",
        (name, json.dumps(data))
    )
    
    dashboard_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return dashboard_id


def get_all_dashboards() -> List[Dict[str, Any]]:
    """Get all dashboards (without full data for listing)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, created_at, updated_at 
        FROM dashboards 
        ORDER BY updated_at DESC
    """)
    
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


# Initialize database on module import
init_db()
