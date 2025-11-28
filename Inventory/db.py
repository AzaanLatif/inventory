import sqlite3

def get_db_connection():
    """Helper function to connect to the SQLite database."""
    conn = sqlite3.connect('inventory.db')
    conn.row_factory = sqlite3.Row
    return conn