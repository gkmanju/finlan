from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db, Base, engine
from ..models import Account
from ..schemas import AccountCreate
from ..auth import get_current_user

Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/accounts", tags=["accounts"]) 


@router.get("/")
def list_accounts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(Account).filter(Account.owner_id == user.id).all()


@router.post("/")
def create_account(payload: AccountCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    acc = Account(name=payload.name, type=payload.type, owner_id=user.id)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
