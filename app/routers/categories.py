from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db, Base, engine
from ..models import Category
from ..schemas import CategoryCreate
from ..auth import get_current_user

Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/categories", tags=["categories"]) 


@router.get("/")
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return db.query(Category).all()


@router.post("/")
def create_category(payload: CategoryCreate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    existing = db.query(Category).filter(Category.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category exists")
    cat = Category(name=payload.name, type=payload.type)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat
