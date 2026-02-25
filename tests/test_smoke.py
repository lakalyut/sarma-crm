from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_redirect():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"].startswith("/admin/products")


#def test_login_page_ok():
#    r = client.get("/login")
#    # если логина нет — убери этот тест, но лучше сразу добавить login
#    assert r.status_code in (200, 404)
