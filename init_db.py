import sqlite3
from datetime import datetime

connection = sqlite3.connect("tickets.db")
cursor = connection.cursor()

create_table_sql = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_email TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    "group" TEXT,
    status TEXT DEFAULT 'Open',
    assigned_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    sla_breached BOOLEAN DEFAULT 0
);
"""

cursor.execute(create_table_sql)

# Optional: Create an index for faster searches
cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON tickets(status);")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_requester ON tickets(requester_email);")

connection.commit()
connection.close()

print("Table 'tickets' is ready.")