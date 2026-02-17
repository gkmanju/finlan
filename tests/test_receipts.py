from datetime import date
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def auth_headers(username="alice", password="secret123"):
    # register
    r = client.post("/auth/register", json={"username": username, "password": password})
    if r.status_code not in (200, 400):
        raise AssertionError(f"register failed: {r.status_code}")
    # login
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    # TestClient stores cookies internally; no headers needed


def test_upload_and_list_and_download_receipt(tmp_path):
    auth_headers()

    # prepare a sample file
    sample = tmp_path / "receipt.txt"
    sample.write_text("test receipt")

    files = {"file": ("receipt.txt", sample.read_bytes(), "text/plain")}
    data = {
        "receipt_date": date.today().isoformat(),
        "provider": "Provider A",
        "service_date": date.today().isoformat(),
        "payment_date": date.today().isoformat(),
        "notes": "Routine check",
    }

    r = client.post("/receipts/", files=files, data=data)
    assert r.status_code == 200
    rid = r.json()["id"]

    r = client.get("/receipts/")
    assert r.status_code == 200
    rows = r.json()
    assert any(row["id"] == rid for row in rows)

    r = client.get(f"/receipts/{rid}/file")
    assert r.status_code == 200
    assert r.headers.get("content-type") in ("text/plain", "application/octet-stream")
