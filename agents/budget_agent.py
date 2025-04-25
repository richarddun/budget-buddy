from pydantic_ai import Agent
from pydantic import BaseModel, field_validator
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai import Agent
import time
import asyncio
import os
from datetime import date
from typing import Optional
from dotenv import load_dotenv
from ynab_sdk_client import YNABSdkClient  # your wrapper
from ynab.exceptions import ApiException, BadRequestException
from urllib3.exceptions import ProtocolError
import socket
from ynab.models import PostScheduledTransactionWrapper, SaveScheduledTransaction
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
    "To create an expected upcoming transaction (e.g., a monthly bill, recurring charge), use create_scheduled_transaction. Supply account ID, date, and amount. Optionally include payee name or category."
    "Scheduled transactions must have dates no more than 7 days in the past and no more than 5 years into the future. If you're unsure, default to next month on the 1st."
    "You can get all the user's scheduled transactions with get_all_scheduled_transactions"
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
    try:
        logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
        return client.get_transactions(BUDGET_ID, input.since_date)
    except (ApiException, ProtocolError, socket.timeout, ConnectionError) as e:
        logger.warning(f"[TOOL ERROR] Network failure: {e}")
        return {
            "error": "There was a network issue contacting the YNAB API. The remote connection was closed unexpectedly. You may try again shortly or ask to continue later."
        }

class GetAllScheduledTransactionsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_all_scheduled_transactions(input: GetAllScheduledTransactionsInput):
    """Retrieve a list of all scheduled transactions from the budget.  Useful to see upcoming costs"""
    logger.info(f"[TOOL] get_all_scheduled_transactions called with budget_id={BUDGET_ID}")
    return client.get_scheduled_transactions(BUDGET_ID)

class CreateScheduledTransactionInput(BaseModel):
    account_id: str
    var_date: date
    amount_eur: float  # now type-safe, thanks to validator
    frequency: str = "monthly"
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None
    flag_color: Optional[str] = None

    @field_validator('amount_eur', mode='before')
    @classmethod
    def parse_amount_eur(cls, v):
        if isinstance(v, (int, float)):
            return float(v)
        try:
            cleaned = str(v).replace("€", "").replace(",", "").strip()
            return float(cleaned)
        except Exception as e:
            raise ValueError(f"Could not parse amount_eur: {v} ({e})")


@budget_agent.tool_plain
def create_scheduled_transaction(input: CreateScheduledTransactionInput):
    """Create a scheduled transaction for a future recurring payment or event. Frequency, amount, date and account are required."""
    logger.info(f"[TOOL] Creating scheduled transaction on account {input.account_id} for €{input.amount_eur} on {input.var_date}")

    amount_milliunits = int(input.amount_eur * 1000)

    detail = SaveScheduledTransaction(
        account_id=input.account_id,
        date=input.var_date,
        amount=amount_milliunits,
        payee_id=input.payee_id,
        payee_name=input.payee_name,
        category_id=input.category_id,
        memo=input.memo,
        flag_color=input.flag_color,
        frequency=input.frequency
    )
    try:
        wrapper = PostScheduledTransactionWrapper(scheduled_transaction=detail)
        response = client.create_scheduled_transaction(BUDGET_ID, wrapper)
    except BadRequestException as e:
        logger.warning(f"[TOOL ERROR] YNAB rejected scheduled transaction: {e}")
        logger.warning(f"[TOOL ERROR] Payload was: {wrapper.to_dict()}")
        return {
            "error": "YNAB rejected the scheduled transaction — the date may be out of range. Please confirm the date is no more than 7 days in the past and not more than 5 years into the future."
        }
    return response.to_dict()


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