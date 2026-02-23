import os
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import HTTPException
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
from .routers import mortgage as mortgage_router
from .routers import tax as tax_router
from .routers import business as business_router
from .auth import get_current_user
from .auth import verify_password

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Personal Finance LAN App")

# Redirect unauthenticated browser requests to login page
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        # API requests (fetch/XHR) expect JSON — return 401 as-is
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

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
app.include_router(mortgage_router.router)
app.include_router(tax_router.router)
app.include_router(business_router.router)

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


@app.get("/equity-awards", response_class=HTMLResponse)
async def equity_awards_page(request: Request, user=Depends(get_current_user)):
    template = jinja_env.get_template("equity_awards.html")
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
    next_url = request.query_params.get('next', '/')
    template = jinja_env.get_template("login.html")
    return template.render(request=request, next_url=next_url)


@app.get("/plaid/oauth-return", response_class=HTMLResponse)
async def plaid_oauth_return(request: Request):
    """OAuth redirect landing page — re-initializes Plaid Link with receivedRedirectUri to complete the OAuth flow."""
    template = jinja_env.get_template("plaid_connect.html")
    return template.render(request=request, oauth_return=True, oauth_redirect_uri=str(request.url))


@app.post("/login")
async def login_form(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    next_url = form.get("next", "/")
    # Safety: only allow relative paths
    if not next_url.startswith("/"):
        next_url = "/"
    from .models import User
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        template = jinja_env.get_template("login.html")
        return HTMLResponse(template.render(request=request, error="Invalid credentials", next_url=next_url), status_code=401)
    from .auth import create_access_token, set_auth_cookie
    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url=next_url, status_code=302)
    set_auth_cookie(response, token)
    return response
