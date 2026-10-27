import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "staging-only-test")
    monkeypatch.setenv("TECMAN_BUILD_MARKER", "test-build")
    monkeypatch.setenv("TECMAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TECMAN_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    module_name = "tecman_demo_password_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_staging_password_and_health(tmp_path, monkeypatch):
    module = _load_app(tmp_path, monkeypatch)
    module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    client = module.app.test_client()

    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/demo-login")

    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json() == {"status": "ok", "build": "test-build"}

    denied = client.post("/demo-login", data={"password": "wrong"})
    assert denied.status_code == 200
    assert "Contraseña incorrecta" in denied.get_data(as_text=True)

    accepted = client.post("/demo-login", data={"password": "staging-only-test"})
    assert accepted.status_code == 302
    assert accepted.headers["Location"].endswith("/")

    page = client.get("/")
    assert page.status_code == 200
