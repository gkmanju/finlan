from app.database import SessionLocal
from app.models import Receipt
from sqlalchemy.orm import joinedload

db = SessionLocal()
r = db.query(Receipt).options(joinedload(Receipt.files)).filter(Receipt.id == 1).first()
print(f"Receipt ID: {r.id}")
print(f"Provider: {r.provider}")
print(f"Files count: {len(r.files)}")
if r.files:
    for f in r.files:
        print(f"  - {f.original_name} (id={f.id})")
else:
    print("  No files!")
db.close()
