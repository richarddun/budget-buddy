from agents.budget_agent import budget_agent
from mcp.server.fastmcp import FastMCP
import asyncio

# Instantiate FastMCP server
app = FastMCP(name="budget-mcp", instructions="Expose budget buddy tools")

# Register all tools from budget_agent
for name, tool in budget_agent._function_tools.items():
    app.add_tool(tool.function, name=name, description=tool.description)

# Simple chat tool that runs the agent with a prompt
@app.tool(name="chat", description="Chat with the budget agent")
async def chat(prompt: str) -> str:
    async with budget_agent.run_stream(prompt) as result:
        output = ""
        async for token in result.stream_text(delta=False):
            output += token
        return output

if __name__ == "__main__":
    app.run(transport="sse")
