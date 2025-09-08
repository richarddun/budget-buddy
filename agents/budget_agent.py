import os
import logging
from dotenv import load_dotenv

load_dotenv()
STAGING = os.getenv("STAGING", "false").lower() in {"1", "true", "yes"}

if STAGING:
    logger = logging.getLogger("uvicorn.error")

    class _DummyResult:
        def __init__(self, prompt: str) -> None:
            self.prompt = prompt
            self.tool_calls = []

        async def stream_text(self, delta: bool = False):
            message = f"[staging] echo: {self.prompt}"
            for ch in message:
                yield ch

    class _DummyContext:
        def __init__(self, prompt: str) -> None:
            self.prompt = prompt

        async def __aenter__(self) -> "_DummyResult":
            return _DummyResult(self.prompt)

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class _DummyAgent:
        async def run_stream(self, prompt: str) -> "_DummyContext":
            return _DummyContext(prompt)

    budget_agent = _DummyAgent()
else:
    from .budget_agent_real import budget_agent  # noqa: F401
