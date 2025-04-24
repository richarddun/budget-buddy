from pydantic_ai import Agent
from pydantic import BaseModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai import Agent
import time
import asyncio
import os
from dotenv import load_dotenv
from ynab_sdk_client import YNABSdkClient  # your wrapper
import logging
logger = logging.getLogger("uvicorn.error")

load_dotenv()
oai_key = os.getenv("OAI_KEY")
BUDGET_ID = os.getenv("YNAB_BUDGET_ID")

# --- LLM Setup ---
oai_model = OpenAIModel(
    model_name='gpt-4.1-mini-2025-04-14',
    provider=OpenAIProvider(api_key=oai_key)
)

budget_agent = Agent(
    model=oai_model,
system_prompt = (
    "You are a proactive budgeting assistant with specialized financial insight. "
    "If the user asks for a budget review or mentions terms like 'review', 'overspent', 'missed payments', or 'flatline', "
    "immediately call get_budget_details to provide an overview. "
    "For questions about specific expenses or transactions, use get_transactions, filtering by date if relevant. "
    "You have full access to the user's budget ID — there is no need to ask them for it. "
    "Use available tools freely and confidently. "
    "Avoid unnecessary repetition or redundant calls. "
    "Speak clearly, keep responses concise, and prioritize utility and financial clarity."
))

# --- Instantiate YNAB SDK Client Once ---
client = YNABSdkClient()

# --- Tool Input Schemas and Bindings ---
class GetAccountsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_accounts(input: GetAccountsInput):
    """Get the list of accounts for a given YNAB budget."""
    return client.get_accounts(BUDGET_ID)

class GetBudgetDetailsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_budget_details(input: GetBudgetDetailsInput):
    """Fetch detailed information about a specific budget."""
    logger.info(f"[TOOL] get_budget_details called with budget_id={BUDGET_ID}")
    return client.get_budget_details(BUDGET_ID)

class GetTransactionsInput(BaseModel):
    budget_id: str
    since_date: str | None = None

@budget_agent.tool_plain
def get_transactions(input: GetTransactionsInput):
    """Retrieve transactions for a budget, optionally since a specific date."""
    logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
    return client.get_transactions(BUDGET_ID, input.since_date)

#class GetFirstBudgetIdInput(BaseModel):
#    pass
#
#@budget_agent.tool_plain
#def get_first_budget_id(input: GetFirstBudgetIdInput):
#    "Get the ID of the first budget associated with the account."
#    return client.get_first_budget_id()

#class GetAllBudgetsOnAccount(BaseModel):
#    pass
#
#@budget_agent.tool_plain
#def get_all_budgets(input: GetAllBudgetsOnAccount):
#    """Retrieve all budget details for high level overview, e.g. Budget ID(s), name, currency settings"""
#    return client.get_all_budgets()

#TODO - account for numeric output of budget amounts, i.e. -774210 = 774.21
# --- Agent Execution ---
async def main():
    user_prompt = "What accounts are tied to my budget right now?"
    async with budget_agent.run_stream(user_prompt) as result:
        async for message in result.stream_text(delta=True):
            for char in message:
                print(char, end="", flush=True)
                time.sleep(0.01)

if __name__ == '__main__':
    asyncio.run(main())