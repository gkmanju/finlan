from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.orm import Session

from ..database import get_db, Base, engine
from ..models import User
from ..schemas import UserCreate
from ..auth import get_password_hash, verify_password, create_access_token, set_auth_cookie, clear_auth_cookie

# Ensure tables exist
Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")
    user = User(username=payload.username, hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username}


@router.post("/login")
def login(payload: UserCreate, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": user.username})
    set_auth_cookie(response, token)
    return {"message": "logged_in"}


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"message": "logged_out"}
