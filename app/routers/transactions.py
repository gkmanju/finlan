from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db, Base, engine
from ..models import Transaction, Account, Category
from ..schemas import TransactionCreate, TransactionRead
from ..auth import get_current_user

# Ensure tables exist
Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/transactions", tags=["transactions"]) 


@router.get("/", response_model=List[TransactionRead])
def list_transactions(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(Transaction)
        .filter(Transaction.user_id == user.id)
        .order_by(Transaction.date.desc())
        .all()
    )
    return rows


@router.post("/", response_model=TransactionRead)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Validate FK existence
    if not db.query(Account).filter(Account.id == payload.account_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if not db.query(Category).filter(Category.id == payload.category_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    txn = Transaction(
        amount=payload.amount,
        date=payload.date,
        notes=payload.notes,
        is_income=payload.is_income,
        user_id=user.id,
        account_id=payload.account_id,
        category_id=payload.category_id,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn
