from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai import Agent
from pydantic_ai.messages import (
    FinalResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ToolCallPartDelta,
)
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

async def test():
    user_prompt = "What's the latest news about space exploration?"
    result = await search_agent.run(user_prompt)
    print(result.output)

async def graph_debug_main():
    user_prompt = "What's the latest news about space exploration?"
    async with search_agent.iter(user_prompt) as run:
        async for node in run:
            print(f"\n📦 Node: {type(node).__name__}")

            if Agent.is_user_prompt_node(node):
                print(f"👤 Prompt: {node.user_prompt}")

            elif Agent.is_model_request_node(node):
                print("🤖 Model Response:")
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, PartStartEvent):
                            print(f"  🔹 Start Part {event.index}")
                        elif isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, TextPartDelta):
                                print(f"  📝 Delta: {event.delta.content_delta}")
                            elif isinstance(event.delta, ToolCallPartDelta):
                                print(f"  🛠️ ToolCallDelta: {event.delta.args_delta}")
                        elif isinstance(event, FinalResultEvent):
                            print(f"  ✅ Final Result: tool_name={event.tool_name}")

            elif Agent.is_call_tools_node(node):
                print("🔧 Tool Execution:")
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, FunctionToolCallEvent):
                            print(f"  📞 Tool Call: {event.part.tool_name} → {event.part.args}")
                        elif isinstance(event, FunctionToolResultEvent):
                            print(f"  📦 Tool Result: {event.result.content}")

            elif Agent.is_end_node(node):
                print(f"🏁 Final Output: {run.result.output}")


async def newmain():
    user_prompt = "Are there any interesting family-friendly events in Arklow, Co. Wicklow tomorrow (Monday 21st April)?"
    async with search_agent.run_stream(user_prompt) as result:
        async for message in result.stream_text(delta=True):
            for char in message:
                print(char, end="", flush=True)
                time.sleep(0.01)

async def main():
    user_prompt = "What's the latest news about space exploration?"
    async with search_agent.iter(user_prompt) as run:
        async for node in run:
            if Agent.is_user_prompt_node(node):
                # A user prompt node => The user has provided input
                output_messages.append(f'=== UserPromptNode: {node.user_prompt} ===')
            elif Agent.is_model_request_node(node):
                # A model request node => We can stream tokens from the model's request
                output_messages.append(
                    '=== ModelRequestNode: streaming partial request tokens ==='
                )
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartStartEvent):
                            output_messages.append(
                                f'[Request] Starting part {event.index}: {event.part!r}'
                            )
                        elif isinstance(event, PartDeltaEvent):
                            if isinstance(event.delta, TextPartDelta):
                                output_messages.append(
                                    f'[Request] Part {event.index} text delta: {event.delta.content_delta!r}'
                                )
                            elif isinstance(event.delta, ToolCallPartDelta):
                                output_messages.append(
                                    f'[Request] Part {event.index} args_delta={event.delta.args_delta}'
                                )
                        elif isinstance(event, FinalResultEvent):
                            output_messages.append(
                                f'[Result] The model produced a final output (tool_name={event.tool_name})'
                            )
            elif Agent.is_call_tools_node(node):
                # A handle-response node => The model returned some data, potentially calls a tool
                output_messages.append(
                    '=== CallToolsNode: streaming partial response & tool usage ==='
                )
                async with node.stream(run.ctx) as handle_stream:
                    async for event in handle_stream:
                        if isinstance(event, FunctionToolCallEvent):
                            output_messages.append(
                                f'[Tools] The LLM calls tool={event.part.tool_name!r} with args={event.part.args} (tool_call_id={event.part.tool_call_id!r})'
                            )
                        elif isinstance(event, FunctionToolResultEvent):
                            output_messages.append(
                                f'[Tools] Tool call {event.tool_call_id!r} returned => {event.result.content}'
                            )
            elif Agent.is_end_node(node):
                assert run.result.output == node.data.output
                # Once an End node is reached, the agent run is complete
                output_messages.append(
                    f'=== Final Agent Output: {run.result.output} ==='
                )


if __name__ == '__main__':
    #asyncio.run(main())
    #asyncio.run(test())
    asyncio.run(newmain())
    #asyncio.run(graph_debug_main())
    print(output_messages)
    with open('model_output.txt','w') as outfile:
        outfile.write(str([x+'\n' for x in output_messages]))