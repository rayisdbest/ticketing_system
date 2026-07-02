import os
from dotenv import load_dotenv
from app import app, db  # Import your established application context & models

load_dotenv()

def initialize_production_database():
    print("🔄 Connecting to PostgreSQL database cluster...")
    
    # We load everything inside the Flask Application context wrapper
    with app.app_context():
        try:
            # Drop tables only if you want to wipe it completely for a clean test:
            # db.drop_all() 
            
            # This triggers SQLAlchemy to build out your Ticket model schema automatically
            db.create_all()
            print("✅ PostgreSQL 'tickets' table generated successfully!")
            
        except Exception as e:
            print(f"❌ Failed to construct database: {str(e)}")
            print("💡 Tip: Verify your database server is running and the database 'tickets_db' actually exists.")

if __name__ == "__main__":
    initialize_production_database()