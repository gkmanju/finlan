# Personal Finance LAN App (FastAPI)

A simple FastAPI + SQLite app to track personal finances on your local network and host on an Ubuntu server.

## Features
- User auth with JWT HttpOnly cookies
- Accounts, categories, transactions CRUD
- Dashboard summary (income, expenses, net)
- CSV import (stub)
- Jinja2 templates + static assets
- HSA receipts: upload, list, download

## Quick Start (Windows dev)

```powershell
# From project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "replace_me"
$env:DATABASE_URL = "sqlite:///./finlan.db"
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Configuration
Copy `.env.example` to `.env` or set environment variables:

- `SECRET_KEY`: random string for JWT
- `ACCESS_TOKEN_EXPIRE_MINUTES`: token lifetime (default 60)
- `DATABASE_URL`: e.g., `sqlite:///./finlan.db`
- `LAN_ALLOWED_HOSTS`: comma-separated IPs/CIDRs allowed
- `ENABLE_GPT5`: optional feature flag, default `false`
- `UPLOAD_DIR`: optional path to store uploaded receipts (default app/uploads)

## Ubuntu Hosting (systemd + Nginx)

```bash
# On Ubuntu server
sudo apt update
sudo apt install python3-venv nginx
cd /opt/finlan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="replace_me"
export DATABASE_URL="sqlite:////opt/finlan/finlan.db"
export UPLOAD_DIR="/opt/finlan/app/uploads"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Create systemd service `/etc/systemd/system/finlan.service` (see deploy/systemd/finlan.service):

```bash
sudo systemctl daemon-reload
sudo systemctl enable finlan
sudo systemctl start finlan
sudo systemctl status finlan
```

Configure Nginx reverse proxy (see deploy/nginx/finlan.conf):

```bash
sudo ln -s /opt/finlan/deploy/nginx/finlan.conf /etc/nginx/sites-available/finlan
sudo ln -s /etc/nginx/sites-available/finlan /etc/nginx/sites-enabled/finlan
sudo nginx -t
sudo systemctl restart nginx
```

## Development Notes
- Default DB is SQLite in project root
- Replace placeholders in `.env.example`
- LAN access should be restricted via network (router/firewall)
- Ensure upload directory exists: `app/uploads/` (auto-created)

## Tests
```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pytest -q
```

## HSA Receipts Usage
- Navigate to `/receipts` (requires login)
- Upload file with metadata: receipt date, provider, service date, payment date, and notes
- See a table of receipts with a download link per row
