import csv
from io import StringIO
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db, Base, engine
from ..models import Transaction, Account, Category
from ..auth import get_current_user

Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/import", tags=["import"]) 


@router.post("/csv")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV supported")

    content = (await file.read()).decode("utf-8", errors="ignore")
    rows = list(csv.DictReader(StringIO(content)))

    created = 0
    for r in rows:
        try:
            amount = float(r.get("amount", "0"))
            is_income = str(r.get("is_income", "false")).strip().lower() in ("1", "true", "yes")
            date_str = r.get("date")
            from datetime import datetime
            txn_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            account_id = int(r.get("account_id"))
            category_id = int(r.get("category_id"))
            notes = r.get("notes")
        except Exception:
            continue

        if not db.query(Account).filter(Account.id == account_id).first():
            continue
        if not db.query(Category).filter(Category.id == category_id).first():
            continue

        txn = Transaction(
            amount=amount,
            date=txn_date,
            notes=notes,
            is_income=is_income,
            user_id=user.id,
            account_id=account_id,
            category_id=category_id,
        )
        db.add(txn)
        created += 1

    db.commit()
    return {"imported": created}
