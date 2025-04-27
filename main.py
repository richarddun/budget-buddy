# main.py
import logging
logger = logging.getLogger("uvicorn.error")
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from agents.budget_agent import budget_agent
import uvicorn
import html
import sqlite3
from pathlib import Path
import asyncio
from ynab_sdk_client import YNABSdkClient as ynab
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

load_dotenv()

# --- Template Setup ---
templates = Jinja2Templates(directory="templates")
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
LOG_FILE = "chat_history_log.json"
DB_PATH = Path("chat_history.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

BUDGET_ID = os.getenv("YNAB_BUDGET_ID")

def store_message(prompt: str, response: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (prompt, response) VALUES (?, ?)", (prompt, response))
    conn.commit()
    conn.close()
    # === Also append to .json log ===
    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "response": response
    }

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump([entry], f, indent=2)
    else:
        with open(LOG_FILE, "r+") as f:
            data = json.load(f)
            data.append(entry)
            f.seek(0)
            json.dump(data, f, indent=2)

def format_chat_history(limit=10):
    history = load_recent_messages(limit)
    return "\n".join([
        f"You: {m['prompt']}\nAgent: {m['response']}" for m in history
    ])

def load_recent_messages(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT prompt, response FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    messages = [{"prompt": row[0], "response": html.unescape(row[1])} for row in reversed(c.fetchall())]
    conn.close()
    return messages

@app.on_event("startup")
async def startup():
    init_db()
    logger.info("[INIT] Budget Buddy (SSE) startup complete.")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    chat_history = load_recent_messages()
    return templates.TemplateResponse("chat.html", {"request": request, "chat_history": chat_history})

@app.get("/budgets")
def get_budget():
    buddy = ynab()
    return buddy.get_budget_details(BUDGET_ID)

@app.post("/htmx-chat", response_class=HTMLResponse)
async def htmx_chat(request: Request, prompt: str = Form(...)):
    return HTMLResponse(f"""
    <p><strong>You:</strong> {prompt}</p>
    <p><strong>Agent:</strong>
        <span id="stream-content"><em>Thinking...</em></span>
        <span id="status-spinner" class="spinner"></span>
    </p>
    <hr>
    """)


@app.get("/sse")
async def sse(prompt: str, fresh: bool = False):
    logger.info(f"[SSE] Incoming stream request with prompt: {prompt}")

    incoming_prompt = prompt.strip()

    if not fresh:
        history = format_chat_history(limit=10)
        if not incoming_prompt.lower().startswith("you:"):
            formatted_prompt = f"You: {incoming_prompt}"
        else:
            formatted_prompt = incoming_prompt
        prompt = f"{history}\n{formatted_prompt}"

    async def event_stream():
        logger.info("[SSE] Stream started")
        full_response = ""
        lnbrk = "\n"
        yield f"retry: 1000{lnbrk}{lnbrk}"
        yield f"event: open{lnbrk}{lnbrk}"

        async with budget_agent.run_stream(prompt) as result:
            logger.info("[SSE] Agent streaming started.")

            # Step 1: Handle any new messages (e.g., tool calls)
            for message in result.new_messages():
                for part in message.parts:
                    # Detect live tool call
                    if isinstance(part, ToolCallPart):
                        tool_name = part.tool_name
                        try:
                            args_json = (
                                part.args.args_json
                                if hasattr(part.args, 'args_json')
                                else json.dumps(part.args.args_dict)
                            )
                        except Exception:
                            args_json = "{}"

                        status_msg = f"🔧 Calling tool: {tool_name}"
                        logger.info(f"[SSE] Live tool call detected: {tool_name}")
                        yield f"event: status{lnbrk}data: {status_msg}{lnbrk}{lnbrk}"
                        await asyncio.sleep(0.1)

                    # (Optional) detect tool return part
                    elif isinstance(part, ToolReturnPart):
                        tool_id = part.tool_call_id
                        status_msg = f"✅ Tool {tool_id} returned."
                        logger.info(f"[SSE] Tool return detected: {tool_id}")
                        yield f"event: status{lnbrk}data: {status_msg}{lnbrk}{lnbrk}"
                        await asyncio.sleep(0.1)

            # Step 2: Stream the normal text tokens
            async for token in result.stream_text(delta=True):
                safe_token = token.replace('\n', '<br>')  # Optional HTML line break handling
                yield f"event: message{lnbrk}data: {safe_token}{lnbrk}{lnbrk}"
                full_response += safe_token
                await asyncio.sleep(0.01)

        logger.info("[SSE] Full response complete, storing...")
        store_message(incoming_prompt, full_response)
        yield f"event: done{lnbrk}data: done{lnbrk}{lnbrk}"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/reset-session")
async def reset_session():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    logger.info("[SESSION] Chat history cleared.")
    return {"status": "ok", "message": "Session reset."}


@app.get("/sse-test")
async def sse_test():
    async def event_stream():
        yield "data: Hello from plain test\n\n"
        await asyncio.sleep(0.5)
        yield "data: This is a working stream\n\n"
        await asyncio.sleep(0.5)
        yield "data: Done\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# Optional CLI testing
async def main():
    user_prompt = "What accounts are tied to my budget right now?"
    async with budget_agent.run_stream(user_prompt) as result:
        async for message in result.stream_text(delta=True):
            for char in message:
                print(char, end="", flush=True)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
