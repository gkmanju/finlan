import os
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .database import Base, engine, get_db
from .models import Transaction
from .routers import auth as auth_router
from .routers import transactions as transactions_router
from .routers import receipts as receipts_router
from .routers import accounts as accounts_router
from .routers import categories as categories_router
from .routers import imports as imports_router
from .routers import portfolio as portfolio_router
from .auth import get_current_user
from .auth import verify_password

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Personal Finance LAN App")

# Static files
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Templates
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(["html", "xml"]),
)

# Feature flag response header middleware
@app.middleware("http")
async def add_feature_headers(request, call_next):
    import os
    response = await call_next(request)
    gpt5_enabled = str(os.getenv("ENABLE_GPT5", "false")).lower() in ("1", "true", "yes")
    response.headers["X-GPT5-Enabled"] = "true" if gpt5_enabled else "false"
    return response

# Routers
app.include_router(auth_router.router, prefix="/auth")
app.include_router(transactions_router.router)
app.include_router(receipts_router.router)
app.include_router(accounts_router.router)
app.include_router(categories_router.router)
app.include_router(imports_router.router)
app.include_router(portfolio_router.router)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    income_total = Decimal("0")
    expense_total = Decimal("0")
    for t in db.query(Transaction).filter(Transaction.user_id == user.id).all():
        if t.is_income:
            income_total += Decimal(str(t.amount))
        else:
            expense_total += Decimal(str(t.amount))
    net = income_total - expense_total

    template = jinja_env.get_template("index.html")
    return template.render(
        request=request,
        username=user.username,
        income_total=str(income_total),
        expense_total=str(expense_total),
        net=str(net),
    )


@app.get("/health")
def health():
    import os
    gpt5_enabled = str(os.getenv("ENABLE_GPT5", "false")).lower() in ("1", "true", "yes")
    return {"status": "ok", "gpt5_enabled": gpt5_enabled}

@app.get("/receipts", response_class=HTMLResponse)
async def receipts_page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    from .models import Receipt
    from sqlalchemy.orm import joinedload
    
    rows = (
        db.query(Receipt)
        .options(joinedload(Receipt.files))
        .filter(Receipt.user_id == user.id)
        .order_by(Receipt.uploaded_at.desc())
        .all()
    )
    
    template = jinja_env.get_template("receipts.html")
    return template.render(request=request, username=user.username, receipts=rows)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("analytics.html")
    return template.render(request=request, username=user.username)


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("portfolio.html")
    return template.render(request=request, username=user.username)


@app.get("/portfolio/upload", response_class=HTMLResponse)
async def portfolio_upload_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("portfolio_upload.html")
    return template.render(request=request, username=user.username)


@app.get("/portfolio/connect", response_class=HTMLResponse)
async def plaid_connect_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("plaid_connect.html")
    return template.render(request=request, username=user.username)


@app.get("/portfolio/credentials", response_class=HTMLResponse)
async def portfolio_credentials_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("broker_credentials.html")
    return template.render(request=request, username=user.username)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    template = jinja_env.get_template("login.html")
    return template.render(request=request)


@app.post("/login")
async def login_form(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    from .models import User
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        template = jinja_env.get_template("login.html")
        return HTMLResponse(template.render(request=request, error="Invalid credentials"), status_code=401)
    from .auth import create_access_token, set_auth_cookie
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/receipts", status_code=302)
    set_auth_cookie(response, token)
    return response
