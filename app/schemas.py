from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, constr


class UserCreate(BaseModel):
    username: constr(min_length=3, max_length=64)
    password: constr(min_length=6, max_length=128)


class UserRead(BaseModel):
    id: int
    username: str
    created_at: datetime

    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AccountCreate(BaseModel):
    name: constr(min_length=1, max_length=100)
    type: constr(min_length=1, max_length=50)


class CategoryCreate(BaseModel):
    name: constr(min_length=1, max_length=100)
    type: constr(min_length=3, max_length=20)


class TransactionCreate(BaseModel):
    amount: float
    date: date
    notes: Optional[str] = None
    is_income: bool = False
    account_id: int
    category_id: int


class TransactionRead(BaseModel):
    id: int
    amount: float
    date: date
    notes: Optional[str]
    is_income: bool
    account_id: int
    category_id: int

    class Config:
        orm_mode = True


class ReceiptFileRead(BaseModel):
    id: int
    file_name: str
    original_name: str
    content_type: Optional[str]
    uploaded_at: datetime

    class Config:
        orm_mode = True


class ReceiptCreate(BaseModel):
    service_date: date
    provider: constr(min_length=1, max_length=150)
    patient_name: Optional[str] = None
    category: Optional[str] = None
    amount: Optional[float] = None
    payment_method: Optional[str] = None
    paid_date: Optional[date] = None
    submitted_date: Optional[date] = None
    reimbursed: bool = False
    reimbursement_amount: Optional[float] = None
    reimbursement_date: Optional[date] = None
    claim_number: Optional[str] = None
    tax_year: Optional[int] = None
    hsa_eligible: bool = True
    notes: Optional[str] = None


class ReceiptRead(BaseModel):
    id: int
    service_date: date
    provider: str
    patient_name: Optional[str]
    category: Optional[str]
    amount: Optional[float]
    payment_method: Optional[str]
    paid_date: Optional[date]
    submitted_date: Optional[date]
    reimbursed: bool
    reimbursement_amount: Optional[float]
    reimbursement_date: Optional[date]
    claim_number: Optional[str]
    tax_year: Optional[int]
    hsa_eligible: bool
    notes: Optional[str]
    uploaded_at: datetime
    files: List[ReceiptFileRead]

    class Config:
        orm_mode = True
