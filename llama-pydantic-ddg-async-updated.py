from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from agent_functions import stream_agent_response
import asyncio
import json

ollama_model = OpenAIModel(
    model_name='llama3.2', provider=OpenAIProvider(base_url='http://localhost:11434/v1')
)
agent = Agent(ollama_model, 
        tools=[duckduckgo_search_tool()],
        system_prompt='Use tools as needed and respond to the user.')

asyncio.run(stream_agent_response(agent, "What's the latest news about space exploration?"))