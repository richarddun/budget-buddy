# 📘 Project README: Family AI Assistant ("Budget Buddy+")

## Overview

**Budget Buddy+** is a personalized AI assistant designed to help manage personal finances through YNAB integration, with future plans to evolve into a multi-skilled household agent. The system leverages LLMs (OpenAI and DeepSeek), `pydantic-ai`, a FastAPI backend, and real-time streaming UI with HTMX and Server-Sent Events (SSE).

---

## 🔧 Current Functionality (v1.0)

### 💼 Budgeting Assistant

#### ✅ Core Features

* **Budget Overview** – Summarizes budget, account, and category information.
* **Transactions** – View, create, and delete individual transactions.
* **Scheduled Payments** – Manage recurring transactions with create, update, and delete operations.
* **Category Budgeting** – Set or update monthly and overall budget targets.
* **Overspending Detection** – Highlights overspent categories automatically.

#### 🔄 Tools & APIs

* Tools implemented using `pydantic.BaseModel` inputs
* Conversion between euros and YNAB milliunits handled automatically
* GET requests use file-backed JSON caching

#### 🌐 Frontend

* HTMX chat interface with Markdown streaming via SSE
* Quick prompt buttons, chat export, session reset
* Upload support for receipts (WIP for OCR)
* Voice input/output toggle (browser speech recognition + synthesis)

#### 🧠 Language Models

* **budget\_agent** uses OpenAI GPT-4.1
* **reasoning\_agent** uses DeepSeek Reasoner for complex planning

---

## 🧪 Architecture Overview

### 🗂️ Project Structure

* `main.py` – FastAPI entrypoint
* `budget_agent.py` – Core assistant + tools
* `ynab_sdk_client.py` – Cached YNAB SDK wrapper
* `chat.html` / `messages.html` – Stream-based chat UI
* `.ynab_cache/` – Cached API responses
* `chat_history.db` – SQLite logging of conversations

---

## 🔮 Future Vision (v2.0+)

### 👪 Multi-Skilled Family Assistant

Planned evolution into a general-purpose agent hub:

| Agent          | Domain                                 |
| -------------- | -------------------------------------- |
| Budget Agent   | Financial planning, YNAB integration   |
| Calendar Agent | Sync with Todoist or Google Calendar   |
| Meal Agent     | Weekly meals + budget-aligned shopping |
| Tutor Agent    | Educational enrichment for kids        |
| Wellness Agent | Journaling, check-ins, reminders       |

Each sub-agent will:

* Expose tool schemas for orchestration
* Return structured output (markdown, JSON, summaries)
* Use memory/state to track family-specific context

### 🔭 Roadmap

*

---

## 🔒 Privacy & Security

* All data local (SQLite, cache)
* YNAB and LLM API keys stored in `.env`
* No tracking or external sync

---

## 📦 Requirements

```
fastapi
uvicorn
python-dotenv
pydantic
pydantic-ai
httpx
jinja2
python-multipart
ynab-sdk
```

---

## 🚀 Running Locally

1. In the repository root folder, create a .env file
2. Add your OpenAI API key, YNAB API token and main YNAB Budget ID like so:

```
YNAB_TOKEN={YNAB_API_KEY}
OAI_KEY={OPENAI_API_KEY}
YNAB_BUDGET_ID={MAIN_YNAB_BUDGET_ID}
```

3. Run the app

```bash
uvicorn main:app --reload
```

Open your browser at [http://localhost:8000](http://localhost:8000)

### Running in staging/offline mode

If you want to start the server without providing real YNAB or OpenAI credentials
set the `STAGING` environment variable. In this mode the app returns placeholder
responses and skips external API calls:

```bash
export STAGING=true
uvicorn main:app --reload
```

This is useful for containerized test environments where secrets are unavailable.

### Optional: Daily 7:00 AM Ingestion

This project can run a time-based job inside the FastAPI/uvicorn process that executes daily at a configured time (defaults to 07:00) to fetch recent transactions and optionally let the AI agent review and adjust categories.

Enable by adding to your `.env`:

```
# Turn the scheduler on
ENABLE_DAILY_INGESTION=true

# Time and timezone
DAILY_INGESTION_HOUR=7
DAILY_INGESTION_MINUTE=0
SCHED_TZ=UTC  # e.g., Europe/Berlin, America/New_York

# Ensure only one instance runs the job
SCHEDULER_LEADER=true  # set false on other replicas/workers

# Optional: allow the AI agent to perform tool-driven adjustments
ENABLE_DAILY_AI_REVIEW=false
```

Notes:
- If you run multiple uvicorn workers or replicas, only one should have `SCHEDULER_LEADER=true` to avoid duplicate executions.
- When developing with `--reload`, prefer leaving the scheduler disabled or ensure only one process is designated as leader.

### Deploying behind a reverse proxy (base path)

If you serve the app under a subpath (e.g., `/budget-buddy/`), set the base path in `config.py`:

```
# config.py
BASE_PATH = "/budget-buddy"
```

The app uses this value as FastAPI's `root_path`, and all links are generated with `request.url_for(...)`, so they respect the base path automatically. Leave `BASE_PATH = ""` for root deployment.

---

## 🧭 Operations Runbooks

See `docs/runbooks.md` for admin runbooks covering ingestion (backfill/delta/CSV), category sync and mapping behavior, basic reconcile steps, and questionnaire exports with hash verification.

---

## 🙌 Acknowledgments

Created by Richard for household use. Powered by open tools, collaborative AI design, and a vision for intelligent family infrastructure.

> "Built with ❤️, tested on chaos, and improved with every grocery run."
