import importlib
import sys
import os
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
    app = load_app()
    client = TestClient(app)
    resp = client.get('/sse', params={'prompt': "How's my budget?"})
    assert 'valid OpenAI API key' in resp.text


def test_missing_ynab_key(monkeypatch):
    monkeypatch.setenv('OAI_KEY', 'test-key')
    monkeypatch.delenv('YNAB_TOKEN', raising=False)
    monkeypatch.delenv('YNAB_BUDGET_ID', raising=False)
    app = load_app()
    client = TestClient(app)
    resp = client.get('/sse', params={'prompt': "How's my budget?"})
    assert "haven't added a YNAB API token" in resp.text
