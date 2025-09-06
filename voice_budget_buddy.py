# voice_budget_buddy.py
import asyncio
import speech_recognition as sr
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import json
import logging
from pyttsx3 import init as tts_init
from agents.budget_agent import budget_agent
from config import BASE_PATH

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-budget-buddy")

# Initialize FastAPI with base path
app = FastAPI(root_path=BASE_PATH)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize TTS engine
tts_engine = tts_init()

# Speech recognizer
recognizer = sr.Recognizer()

@app.get("/", response_class=HTMLResponse)
async def get_index(request):
    return templates.TemplateResponse("voice_index.html", {"request": request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Receive audio data from client
            audio_data = await websocket.receive_bytes()

            # Process audio to text
            text = await process_audio(audio_data)
            await websocket.send_json({"type": "transcript", "text": text})

            # Get response from budget agent
            response_text = await get_agent_response(text)

            # Convert response to speech
            audio_path = text_to_speech(response_text)

            # Send response back to client
            await websocket.send_json({
                "type": "response",
                "text": response_text,
                "audio_url": f"static/audio/{audio_path}"
            })
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

async def process_audio(audio_data):
    """Convert audio data to text using speech recognition"""
    try:
        # Save audio data to a temporary file
        with open("temp_audio.wav", "wb") as f:
            f.write(audio_data)

        # Use speech recognition
        with sr.AudioFile("temp_audio.wav") as source:
            audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
            return text
    except Exception as e:
        logger.error(f"Speech recognition error: {e}")
        return "Sorry, I couldn't understand that."

async def get_agent_response(text):
    """Get response from budget agent"""
    try:
        response = ""
        async with budget_agent.run_stream(text) as result:
            async for token in result.stream_text():
                response += token
        return response
    except Exception as e:
        logger.error(f"Agent error: {e}")
        return "Sorry, I encountered an error processing your request."

def text_to_speech(text):
    """Convert text to speech and save as audio file"""
    try:
        # Generate a unique filename
        import uuid
        filename = f"{uuid.uuid4()}.mp3"
        file_path = f"static/audio/{filename}"

        # Ensure directory exists
        import os
        os.makedirs("static/audio", exist_ok=True)

        # Generate speech
        tts_engine.save_to_file(text, file_path)
        tts_engine.runAndWait()

        return filename
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None

if __name__ == "__main__":
    uvicorn.run("voice_budget_buddy:app", host="0.0.0.0", port=8000, reload=True)

