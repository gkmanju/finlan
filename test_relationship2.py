from app.database import SessionLocal
from app.models import Receipt, ReceiptFile
from sqlalchemy.orm import joinedload

db = SessionLocal()

# Try querying ReceiptFile and accessing receipt
print("=== Test 1: Query ReceiptFile ===")
rf = db.query(ReceiptFile).filter(ReceiptFile.receipt_id == 66).first()
if rf:
    print(f"ReceiptFile ID: {rf.id}, Receipt ID: {rf.receipt_id}")
    print(f"File: {rf.original_name}")
    print(f"Receipt: {rf.receipt}")
    print(f"Receipt provider: {rf.receipt.provider}")

print("\n=== Test 2: Query Receipt with joinedload ===")
r = db.query(Receipt).options(joinedload(Receipt.files)).filter(Receipt.id == 66).first()
print(f"Receipt ID: {r.id}, Provider: {r.provider}")
print(f"Files attribute type: {type(r.files)}")
print(f"Files count: {len(r.files)}")
print(f"Files: {r.files}")

print("\n=== Test 3: Direct SQL ===")
from sqlalchemy import text
result = db.execute(text("SELECT COUNT(*) FROM receipt_files WHERE receipt_id = 66"))
count = result.scalar()
print(f"SQL count of files for receipt 66: {count}")

db.close()
