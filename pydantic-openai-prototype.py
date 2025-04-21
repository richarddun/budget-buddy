from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai import Agent
import time
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
oai_key = os.getenv("OAI_KEY")

oai_model = OpenAIModel(
    model_name='gpt-4.1-mini-2025-04-14', provider=OpenAIProvider(api_key=oai_key)
)
search_agent = Agent(oai_model, 
        tools=[duckduckgo_search_tool()],
        system_prompt='Search the internet and assist the user with their questions.')


output_messages: list[str] = []


async def main():
    user_prompt = "Are there any interesting family-friendly events in Arklow, Co. Wicklow tomorrow (Monday 21st April)?"
    async with search_agent.run_stream(user_prompt) as result:
        async for message in result.stream_text(delta=True):
            for char in message:
                print(char, end="", flush=True)
                time.sleep(0.01)

if __name__ == '__main__':
    asyncio.run(main())