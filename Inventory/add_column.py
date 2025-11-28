import sqlite3
import os

# --- Make sure this is the correct path to your database file ---
DATABASE_FILE = os.path.join(os.path.dirname(__file__), 'inventory.db')

def add_column():
    """Adds the bill_image column to the purchases table if it doesn't exist."""
    if not os.path.exists(DATABASE_FILE):
        print(f"Error: Database file not found at '{DATABASE_FILE}'")
        return

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        # Check if the column already exists
        cursor.execute("PRAGMA table_info(purchases)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'bill_image' not in columns:
            print("Adding 'bill_image' column to 'purchases' table...")
            cursor.execute("ALTER TABLE purchases ADD COLUMN bill_image TEXT")
            conn.commit()
            print("Column 'bill_image' added successfully.")
        else:
            print("Column 'bill_image' already exists.")

        conn.close()

    except sqlite3.Error as e:
        print(f"Database error: {e}")

if __name__ == '__main__':
    add_column()