"""Run inside the built image against an empty, disposable PostgreSQL database."""

import io
import os
import subprocess
import sys
import time

import httpx
import pandas as pd


def main():
    # Never run this against production: it seeds an admin and a test sale.
    if os.getenv("IMAGE_SMOKE_TEST") != "1":
        raise RuntimeError(
            "IMAGE_SMOKE_TEST=1 is required for a disposable test database"
        )
    os.environ["TELEGRAM_POLLING_ENABLED"] = "0"
    os.environ["TELEGRAM_TOKEN"] = ""
    os.environ["ADMIN_EMAIL"] = ""
    os.environ["ADMIN_PASSWORD"] = ""
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "app.release_updates"], check=True)

    from app.auth_models import SessionModel, User, default_expiry
    from app.auth_security import hash_password, verify_password
    from app.database import SessionLocal
    from app.models import EventLog, Product, Sale
    from app.product_parser import normalize_text

    password_hash = hash_password("image-smoke-password")
    assert verify_password("image-smoke-password", password_hash)
    with SessionLocal() as db:
        user = User(
            email="image-smoke@test.local",
            role="admin",
            is_active=True,
            password_hash=password_hash,
        )
        db.add(user)
        db.flush()
        db.add(
            SessionModel(
                id="image-smoke-session",
                user_id=user.id,
                expires_at=default_expiry(hours=1),
            )
        )
        sku = 'Табак для кальяна "Smoke" Малина'
        product = Product(
            category="Табак для кальяна",
            brand="Smoke",
            flavor="Малина",
            canonical_sku=sku,
            canonical_name=sku + " 120г.",
            default_weight_g=120,
            norm_brand="smoke",
            norm_flavor=normalize_text("Малина"),
            is_active=True,
        )
        db.add(product)
        db.commit()
        product_id = product.id

    buffer = io.BytesIO()
    pd.DataFrame(
        [
            {
                "Месяц": "2026-01-01",
                "Тип": "HoReCa",
                "Клиент": "Smoke client",
                "Номенклатура": sku + " 120г.",
                "SKU": "RAW-SMOKE",
                "Количество": 2,
                "Вес": 0.24,
            }
        ]
    ).to_excel(buffer, index=False)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18001",
        ]
    )
    try:
        with httpx.Client(
            base_url="http://127.0.0.1:18001", trust_env=False, timeout=5
        ) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Web process exited before readiness")
                try:
                    response = client.get("/ready")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Readiness timeout")
            assert response.json() == {"status": "ok"}
            assert client.get("/auth/login").status_code == 200
            assert client.get("/static/favicon.svg").status_code == 200
            assert client.get("/static/css/loading.css").status_code == 200
            headers = {
                "Cookie": "session_id=image-smoke-session; csrf_token=image-smoke-csrf"
            }
            response = client.post(
                "/import-xlsx",
                headers=headers,
                data={"city": "Smoke city", "csrf_token": "image-smoke-csrf"},
                files={
                    "file": (
                        "smoke.xlsx",
                        buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
            assert response.status_code == 200
            assert "Импортировано строк: 1" in response.text
            response = client.get(
                "/analytics/clients", params={"city": "Smoke city"}, headers=headers
            )
            assert response.status_code == 200
            assert "Smoke client" in response.text
        with SessionLocal() as db:
            sale = db.query(Sale).filter_by(city="Smoke city").one()
            assert sale.matched and sale.product_id == product_id
            assert sale.qty == 2 and sale.weight == 0.24
            assert (
                db.query(EventLog).filter_by(city="Smoke city").one().rows_imported == 1
            )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    print(
        "Image smoke checks passed: dependencies, PostgreSQL migrations, release drafts, bcrypt, HTTP readiness, assets, XLSX import and client analytics"
    )


if __name__ == "__main__":
    main()
