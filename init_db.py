import sqlite3

# 1. Connect to the database (it will create 'tickets.db' automatically)
connection = sqlite3.connect("tickets.db")

# 2. Create a cursor object to execute SQL commands
cursor = connection.cursor()

# 3. Write the SQL statement to create your custom tickets table
create_table_sql = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    "group" TEXT NOT NULL,
    status TEXT DEFAULT 'Open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    assigned_agent TEXT
);
"""

# 4. Execute the SQL command
cursor.execute(create_table_sql)

# 5. Commit changes and close the connection
connection.commit()
connection.close()

print("Database initialized and 'tickets' table created successfully!")