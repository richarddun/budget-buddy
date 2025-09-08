import importlib
import sys
import os

# Ensure the project root is on the path so `import main` succeeds when tests
# are executed from within the `tests` directory.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from fastapi.testclient import TestClient


def load_app():
    if 'main' in sys.modules:
        importlib.reload(sys.modules['main'])
    else:
        import main  # noqa: F401
    return sys.modules['main'].app


def test_missing_openai_key(monkeypatch):
    monkeypatch.delenv('OAI_KEY', raising=False)
    monkeypatch.delenv('YNAB_TOKEN', raising=False)
    monkeypatch.delenv('YNAB_BUDGET_ID', raising=False)
    monkeypatch.setenv('STAGING', 'false')
    app = load_app()
    with TestClient(app) as client:
        resp = client.get('/sse', params={'prompt': "How's my budget?"})
        assert 'valid OpenAI API key' in resp.text


def test_missing_ynab_key(monkeypatch):
    monkeypatch.setenv('OAI_KEY', 'test-key')
    monkeypatch.delenv('YNAB_TOKEN', raising=False)
    monkeypatch.delenv('YNAB_BUDGET_ID', raising=False)
    monkeypatch.setenv('STAGING', 'false')
    app = load_app()
    with TestClient(app) as client:
        resp = client.get('/sse', params={'prompt': "How's my budget?"})
        assert "haven't added a YNAB API token" in resp.text
