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
* `reasoning_agent.py` – DeepSeek-powered logic engine
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
uvicorn==0.29.0
python-dotenv==1.0.1
pydantic
pydantic-ai
httpx
jinja2==3.1.3
python-multipart==0.0.9
ynab-sdk==0.0.1
ollama==0.1.7
ynab
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

---

## 🙌 Acknowledgments

Created by Richard for household use. Powered by open tools, collaborative AI design, and a vision for intelligent family infrastructure.

> "Built with ❤️, tested on chaos, and improved with every grocery run."
