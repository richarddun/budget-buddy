import json
from pydantic_ai import Agent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

async def stream_agent_response(agent: Agent, prompt: str):
    print(f"\n🧠 Prompt: {prompt}\n")

    async with agent.run_stream(prompt) as result:
        # Step 1: Handle any initial model messages (tool calls, etc.)
        for message in result.new_messages():
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    args = (
                        part.args.args_json
                        if hasattr(part.args, 'args_json')
                        else json.dumps(part.args.args_dict)
                    )
                    print(f"🛠️ Tool Call: {part.tool_name}")
                    print(f"   Parameters: {args}\n")

                elif isinstance(part, ToolReturnPart):
                    print(f"🔁 Tool Result (from {part.tool_call_id}):")
                    print(f"{json.dumps(part.content, indent=2)}\n")

        # Step 2: Stream the final assistant response
        print("💬 Assistant:")
        async for token in result.stream_text():
            print(token, end="", flush=True)

        print("\n")
