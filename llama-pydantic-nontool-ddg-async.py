from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
import asyncio

ollama_model = OpenAIModel(
    model_name='llama3.2', provider=OpenAIProvider(base_url='http://localhost:11434/v1')
)
agent = Agent(ollama_model, 
        system_prompt='You are a helpful assistant.')

async def main():
    async with agent.run_stream('Tell me an interesting fact about water') as result:
        async for message in result.stream_text(delta=True):
            print(message)
"""
Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65, details=None)
"""
if __name__=='__main__':
    asyncio.run(main())