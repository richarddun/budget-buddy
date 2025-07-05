# reasoning_agent.py
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from httpx import AsyncClient
from pydantic_ai.providers.deepseek import DeepSeekProvider
import os
from dotenv import load_dotenv

load_dotenv()
deepseek_key = os.getenv("DEEPSEEK_API_KEY")
if deepseek_key is None:
    raise ValueError("DEEPSEEK_API_KEY environment variable is not set, check your .env file!")
custom_http_client = AsyncClient(timeout=30)
# DeepSeek behaves like OpenAI — just change base_url
deepseek_model = OpenAIModel(
    model_name='deepseek-reasoner',  # or whatever exact name you're targeting
    provider=DeepSeekProvider(
        api_key=deepseek_key,
        http_client=custom_http_client
    )
)

reasoning_agent = Agent(
    model=deepseek_model,
    system_prompt=(
        "You are an advanced reasoning assistant specialized in financial planning and budget analysis.\n"
        "When given a complex request, break down the steps logically and provide a clear, structured answer.\n"
        "Use multiple steps of reasoning, comparisons, or calculations if needed.\n"
        "Be efficient with your output and prioritize clarity."
    )
)
