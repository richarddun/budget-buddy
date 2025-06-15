# main.py
import logging
logger = logging.getLogger("uvicorn.error")
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from agents.budget_agent import budget_agent
import uvicorn
import html
import sqlite3
from pathlib import Path
from typing import List
import asyncio
from ynab_sdk_client import YNABSdkClient as ynab
import os
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def check_api_keys():
    """Return a warning message if API keys are missing."""
    if os.getenv("OAI_KEY") is None:
        logger.info("OpenAI API key missing. Returning instructional message.")
        return (
            "Looks like you don't have a valid OpenAI API key.  Go to platform.openai.com "
            "and generate a new key, then add it to your .env file (in the root folder of the repository you cloned).  "
            "Please try again then."
        )
    if os.getenv("YNAB_TOKEN") is None:
        logger.info("YNAB API token missing. Returning instructional message.")
        return (
            "It looks like you haven't added a YNAB API token to your .env file, I can't view your budget without it.  "
            "Go to https://api.ynab.com/ and generate a token, and add to your .env file.  Please try again then."
        )
    return None



# --- Template Setup ---
templates = Jinja2Templates(directory="templates")
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
LOG_FILE = "chat_history_log.json"
DB_PATH = Path("chat_history.db")

# --- File upload Setup ---
UPLOAD_DIR = Path("uploaded_receipts")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/receipts", StaticFiles(directory=UPLOAD_DIR), name="receipts")

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
    # Ensure database and table exist
    if not DB_PATH.exists():
        init_db()

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

    incoming_prompt = prompt.strip()  # capture clean user input

    missing_msg = check_api_keys()
    if missing_msg:
        async def event_stream_missing():
            logger.info("[SSE] Missing API keys; sending static message")
            lnbrk = "\n"
            yield "retry: 1000\n\n"
            yield f"event: message{lnbrk}data: {missing_msg}{lnbrk}{lnbrk}"
            store_message(incoming_prompt, missing_msg)
            yield f"event: done{lnbrk}data: done{lnbrk}{lnbrk}"

        return StreamingResponse(event_stream_missing(), media_type="text/event-stream")

    if not fresh:
        history = format_chat_history(limit=10)
        if not incoming_prompt.lower().startswith("you:"):
            formatted_prompt = f"You: {incoming_prompt}"
        else:
            formatted_prompt = incoming_prompt
        prompt = f"{history}\n{formatted_prompt}"

    logger.info(f"[SSE] Final prompt sent to agent: {repr(prompt[:120])}...")

    async def event_stream():
        logger.info("[SSE] Stream started")
        full_response = ""
        lnbrk = "\n"
        yield "retry: 1000\n\n"
        yield "event: open\n\n"
        logger.info("[SSE] Heading into agent-runstream..")
        async with budget_agent.run_stream(prompt) as result:
            # Emit status messages from tool responses if present
            if hasattr(result, "tool_calls") and result.tool_calls:
                for call in result.tool_calls:
                    tool_output = call.output
                    if isinstance(tool_output, dict) and "status" in tool_output:
                        status_msg = tool_output["status"]
                        logger.info(f"[SSE] Status from tool: {status_msg}")
                        yield f"event: status{lnbrk}data: {status_msg}{lnbrk}{lnbrk}"
                        await asyncio.sleep(0.1)  # slight pause to let UI update

            # Begin token streaming
            async for token in result.stream_text(delta=True):
                logger.info(f"[SSE] Token received: {repr(token)}")
                safe_token = token.replace('\n', '<br>')
                #safe_token = token
                yield f"event: message{lnbrk}data: {safe_token}{lnbrk}{lnbrk}"
                full_response += safe_token
                await asyncio.sleep(0.01)

        logger.info("[SSE] Full response assembled, storing...")
        store_message(incoming_prompt, full_response)
        yield f"event: done\ndata: done\n\n"

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

@app.post("/upload-receipt")
async def upload_receipt(files: List[UploadFile] = File(...)):
    uploaded_filenames = []

    for file in files:
        try:
            contents = await file.read()
            file_path = UPLOAD_DIR / file.filename
            with open(file_path, "wb") as f:
                f.write(contents)
            uploaded_filenames.append(file.filename)
            logger.info(f"[UPLOAD] Saved receipt to {file_path}")
        except Exception as e:
            logger.error(f"[UPLOAD ERROR] {e}")
            return {"status": "error", "detail": str(e)}

    return {"status": "success", "filenames": uploaded_filenames}

from fastapi.responses import HTMLResponse

@app.get("/uploads", response_class=HTMLResponse)
async def view_uploads():
    files = [f.name for f in UPLOAD_DIR.iterdir() if f.is_file()]
    
    # Generate HTML gallery
    images_html = ""
    for file in files:
        images_html += f"""
        <div style="display:inline-block; margin:10px; text-align:center;">
            <a href="/receipts/{file}" target="_blank">
                <img src="/receipts/{file}" style="width:150px; height:auto; border-radius:8px; box-shadow:0 0 5px #aaa;">
            </a>
            <div style="margin-top:5px; font-size:0.9em; color:#ccc;">{file}</div>
        </div>
        """

    page_html = f"""
    <html>
    <head>
    <title>Uploaded Receipts</title>
    <style>
        body {{
            background-color: #1e1e2f;
            color: #ddd;
            font-family: 'Segoe UI', sans-serif;
            text-align: center;
        }}
        h1 {{
            margin-top: 20px;
        }}
    </style>
    </head>
    <body>
    <div id="backlink"><a href="/" style="display:inline-block; margin:15px; padding:10px 20px; background:#4477dd; color:white; text-decoration:none; border-radius:8px;">⬅️ Back to Chat</a></div>
    <h1>📂 Uploaded Receipts</h1>
    {images_html if images_html else "<p>No receipts uploaded yet.</p>"}
    </body>
    </html>
    """
    return HTMLResponse(content=page_html)

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
