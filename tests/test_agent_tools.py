from __future__ import annotations

import importlib
from types import ModuleType
from datetime import date, timedelta
from pathlib import Path
import sqlite3

import os

from db.migrate import run_migrations


def _fake_agent_modules(monkeypatch):
    """Inject lightweight fakes for pydantic_ai and ynab model submodules so we can import agent tooling without heavy deps."""
    # pydantic_ai
    pai = ModuleType("pydantic_ai")

    class _DummyAgent:
        def __init__(self, *args, **kwargs):
            pass

        def tool_plain(self, fn):
            # Decorator passthrough
            return fn

        async def run(self, prompt: str):  # pragma: no cover - not used in these tests
            return {"echo": prompt}

    pai.Agent = _DummyAgent
    monkeypatch.setitem(os.sys.modules, "pydantic_ai", pai)

    models_openai = ModuleType("pydantic_ai.models.openai")

    class _DummyModel:
        def __init__(self, *args, **kwargs):
            pass

    models_openai.OpenAIModel = _DummyModel
    monkeypatch.setitem(os.sys.modules, "pydantic_ai.models.openai", models_openai)

    providers_openai = ModuleType("pydantic_ai.providers.openai")

    class _DummyProvider:
        def __init__(self, *args, **kwargs):
            pass

    providers_openai.OpenAIProvider = _DummyProvider
    monkeypatch.setitem(os.sys.modules, "pydantic_ai.providers.openai", providers_openai)

    # ynab exceptions/models used only for type imports in the agent module
    ynab_ex = ModuleType("ynab.exceptions")

    class _ApiException(Exception):
        pass

    class _BadRequestException(Exception):
        pass

    ynab_ex.ApiException = _ApiException
    ynab_ex.BadRequestException = _BadRequestException
    monkeypatch.setitem(os.sys.modules, "ynab.exceptions", ynab_ex)

    # Stub each referenced ynab.models.* module with an empty class of the expected name
    def _stub(submodule: str, cls_name: str):
        mod = ModuleType(f"ynab.models.{submodule}")
        cls = type(cls_name, (), {})
        setattr(mod, cls_name, cls)
        monkeypatch.setitem(os.sys.modules, f"ynab.models.{submodule}", mod)

    _stub("post_scheduled_transaction_wrapper", "PostScheduledTransactionWrapper")
    _stub("save_scheduled_transaction", "SaveScheduledTransaction")
    _stub("patch_month_category_wrapper", "PatchMonthCategoryWrapper")
    # For enums, simple containers with attributes is sufficient
    enum_freq = ModuleType("ynab.models.scheduled_transaction_frequency")
    for name in [
        "MONTHLY",
        "WEEKLY",
        "YEARLY",
        "EVERYOTHERMONTH",
        "EVERYOTHERWEEK",
        "EVERY4WEEKS",
        "TWICEAMONTH",
        "DAILY",
        "NEVER",
    ]:
        setattr(enum_freq, name, name)
    monkeypatch.setitem(os.sys.modules, "ynab.models.scheduled_transaction_frequency", enum_freq)

    enum_flag = ModuleType("ynab.models.transaction_flag_color")
    for name in ["RED", "ORANGE", "YELLOW", "GREEN", "BLUE", "PURPLE"]:
        setattr(enum_flag, name.upper(), name.upper())
    monkeypatch.setitem(os.sys.modules, "ynab.models.transaction_flag_color", enum_flag)

    _stub("post_transactions_wrapper", "PostTransactionsWrapper")
    _stub("save_transaction_with_optional_fields", "SaveTransactionWithOptionalFields")
    _stub("save_transaction_with_id_or_import_id", "SaveTransactionWithIdOrImportId")


def _init_db(db_path: Path) -> None:
    run_migrations(db_path)
    # Ensure there is at least one active account for commitment insertions
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO accounts(id, name, type, currency, is_active) VALUES (1, 'Checking', 'depository', 'USD', 1)"
        )
        conn.commit()
    finally:
        conn.close()


def test_add_and_delete_key_event_tool(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_tools.db"
    _init_db(db_path)
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    _fake_agent_modules(monkeypatch)

    # Import after stubbing heavy deps
    mod = importlib.import_module("agents.budget_agent_real")

    payload = mod.AddKeyEventInput(
        name="Birthday",
        event_date=date(2025, 12, 12),
        planned_amount_eur=150.0,
        repeat_rule="ANNUAL",
        shift_policy="AS_SCHEDULED",
    )
    resp = mod.add_key_event(payload)
    assert resp["status"] == "key_event_saved"
    ev = resp["event"]
    assert ev["name"] == "Birthday"
    assert ev["event_date"] == "2025-12-12"
    assert ev["planned_amount_cents"] == 15000

    # Verify persisted
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM key_spend_events WHERE id = ?", (ev["id"],)).fetchone()
        assert int(row[0]) == 1
    finally:
        conn.close()

    # Delete
    del_resp = mod.delete_key_event(mod.DeleteKeyEventInput(id=ev["id"]))
    assert del_resp["status"] == "deleted"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM key_spend_events WHERE id = ?", (ev["id"],)).fetchone()
        assert int(row[0]) == 0
    finally:
        conn.close()


def test_add_and_delete_commitment_tool(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_tools_commitments.db"
    _init_db(db_path)
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    _fake_agent_modules(monkeypatch)

    mod = importlib.import_module("agents.budget_agent_real")

    payload = mod.AddCommitmentInput(
        name="Rent",
        amount_eur=1200.0,
        due_rule="MONTHLY",
        next_due_date=date(2025, 1, 1),
        type="rent",
    )
    resp = mod.add_commitment(payload)
    assert resp["status"] == "commitment_saved"
    c = resp["commitment"]
    assert c["name"] == "Rent"
    assert int(c["amount_cents"]) == 120000
    assert c["due_rule"] == "MONTHLY"
    assert c["type"] == "rent"

    # Verify persisted
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM commitments WHERE id = ?", (c["id"],)).fetchone()
        assert int(row[0]) == 1
    finally:
        conn.close()

    # Delete
    del_resp = mod.delete_commitment(mod.DeleteCommitmentInput(id=c["id"]))
    assert del_resp["status"] == "deleted"


def test_detect_commitment_candidates(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_tools_detect.db"
    _init_db(db_path)
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    # Keep analyzer local; stub heavy deps for import
    _fake_agent_modules(monkeypatch)

    mod = importlib.import_module("agents.budget_agent_real")

    # Monkeypatch analyzer to avoid network and inject synthetic recurring transactions
    def _fake_load(self):
        # Three monthly debits to the same payee around day 5
        base = date(2025, 1, 5)
        self._budget_data = {}
        self._transaction_data = [
            {"id": "t1", "payee_name": "ACME MORTGAGE", "amount": -999.0, "date": base.isoformat()},
            {"id": "t2", "payee_name": "ACME MORTGAGE", "amount": -1001.5, "date": (base + timedelta(days=31)).isoformat()},
            {"id": "t3", "payee_name": "ACME MORTGAGE", "amount": -1000.2, "date": (base + timedelta(days=62)).isoformat()},
            # Some noise
            {"id": "n1", "payee_name": "STREAMFLIX", "amount": -12.99, "date": (base + timedelta(days=3)).isoformat()},
        ]

    monkeypatch.setattr(mod.BudgetHealthAnalyzer, "_load_data", _fake_load, raising=True)

    resp = mod.detect_commitment_candidates(mod.DetectCommitmentCandidatesInput(min_confidence=0, min_avg_amount_eur=10.0, limit=10))
    cands = resp.get("candidates", [])
    names = [c.get("name") for c in cands]
    assert any("ACME MORTGAGE" == n for n in names)
    acme = next(c for c in cands if c.get("name") == "ACME MORTGAGE")
    assert acme.get("type") in ("mortgage", "bill")
    # suggested_day_of_month provided by recurring detector when available
    assert isinstance(acme.get("suggested_day_of_month"), (int, type(None)))

