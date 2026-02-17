"""
Migration script to restructure receipts table:
- Create receipt_files table
- Move file data from receipts to receipt_files
- Keep original receipts table intact (don't drop columns for safety)
"""

from app.database import engine, Base
from sqlalchemy import text

def migrate():
    """Perform database migration"""
    
    with engine.begin() as conn:
        print("Starting migration...")
        
        # Check if receipt_files table already exists
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='receipt_files'"))
        if result.fetchone():
            print("receipt_files table already exists. Checking for data...")
            count = conn.execute(text("SELECT COUNT(*) FROM receipt_files")).fetchone()[0]
            if count > 0:
                print(f"Migration already completed - {count} files in receipt_files table")
                return
        
        # Create receipt_files table
        print("Creating receipt_files table...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS receipt_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER NOT NULL,
                file_name VARCHAR NOT NULL,
                original_name VARCHAR NOT NULL,
                content_type VARCHAR,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (receipt_id) REFERENCES receipts (id) ON DELETE CASCADE
            )
        """))
        
        # Check if old columns exist
        result = conn.execute(text("PRAGMA table_info(receipts)"))
        columns = {row[1] for row in result}
        
        if 'file_name' in columns:
            print("Migrating existing receipt data to receipt_files...")
            # Copy existing receipt file data to receipt_files
            conn.execute(text("""
                INSERT INTO receipt_files (receipt_id, file_name, original_name, content_type, uploaded_at)
                SELECT id, file_name, original_name, 
                       COALESCE(content_type, 'application/octet-stream'),
                       uploaded_at
                FROM receipts
                WHERE file_name IS NOT NULL AND file_name != ''
            """))
            
            rows_migrated = conn.execute(text("SELECT COUNT(*) FROM receipt_files")).fetchone()[0]
            print(f"Successfully migrated {rows_migrated} files to receipt_files table")
            print("Original receipts table columns preserved for safety")
            print("Migration completed successfully!")
        else:
            print("Receipts table already migrated (no file_name column found)")
            print("Migration skipped.")

if __name__ == "__main__":
    migrate()
