from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_redirect():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"].startswith("/admin/products")
