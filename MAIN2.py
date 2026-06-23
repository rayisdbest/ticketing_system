from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3

app = FastAPI()
# Enable CORS so your frontend HTML can talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In development, allow any frontend to connect
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This is a Pydantic Model. It ensures Person A sends the exact fields required.
class TicketCreate(BaseModel):
    requester_name: str
    subject: str
    description: Optional[str] = None
    category: str
    priority: str
    group: str
    


# Helper function to connect to your SQLite database file
def get_db_connection():
    conn = sqlite3.connect("tickets.db")
    conn.row_factory = sqlite3.Row  # This allows us to access data like a dictionary
    return conn


# --- ROUTE 2 (For Person B): Get & Filter the Queue ---
@app.get("/api/tickets")
def get_tickets(
    status: Optional[str] = None, 
    priority: Optional[str] = None, 
    group: Optional[str] = None
):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Base SQL query
    query = 'SELECT * FROM tickets WHERE 1=1'
    params = []
    
    # Dynamic filtering logic for your Admin Queue
    if status:
        query += ' AND status = ?'
        params.append(status)
    if priority:
        query += ' AND priority = ?'
        params.append(priority)
    if group:
        query += ' AND "group" = ?'
        params.append(group)
        
    query += ' ORDER BY id DESC' # Newest tickets first
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert database rows into standard Python dictionaries for the frontend
    return [dict(row) for row in rows]