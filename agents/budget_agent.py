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

today = date.today().strftime("%B %d, %Y")

budget_agent = Agent(
    model=oai_model,
system_prompt = (
    "You are a proactive budgeting assistant with specialized financial insight. "
    f"Today is {today}. When reasoning about dates, assume today's date is accurate.\n"
    "If the user asks for a budget review or mentions terms like 'review', 'overspent', 'missed payments', or 'flatline', "
    "immediately call get_budget_details to provide an overview. "
    "For questions about specific expenses or transactions, use get_transactions, filtering by date if relevant. "
    "You have full access to the user's budget ID — there is no need to ask them for it. "
    "To create an expected upcoming transaction (e.g., a monthly bill, recurring charge), use create_scheduled_transaction. Supply account ID, date, and amount. Optionally include payee name or category. "
    "Scheduled transactions must have dates no more than 7 days in the past and no more than 5 years into the future. If you're unsure, default to next month on the 1st. "
    "You can get all the user's scheduled transactions with get_all_scheduled_transactions. "
    "For any tool that involves an account ID (such as transaction related tools) assume you're operating on the account 'CURRENT-166' unless the user specifies otherwise. "
    "Use available tools freely and confidently. "
    "Avoid unnecessary repetition or redundant calls. "
    "Speak clearly, keep responses concise, and prioritize utility and financial clarity.\n"

    "If the user asks about overspending, overbudgeting, category issues, or mentions 'where am I overspending', call get_overspent_categories to provide a list of problem areas. "
    "If the user mentions modifying a scheduled payment (such as 'change my rent', 'edit my Netflix payment', or 'update my scheduled transactions'), call update_scheduled_transaction. "
    "If the user mentions canceling a future bill or subscription ('cancel', 'stop', 'delete a scheduled transaction'), call delete_scheduled_transaction. "
    "If the user says they want to add a real transaction ('log my coffee', 'record a grocery purchase', 'add a transaction'), call create_transaction, assuming today's date unless they specify otherwise. "
    "If the user asks to remove or delete a real transaction ('delete a wrong transaction', 'remove an expense'), call delete_transaction. "
    "Default account is CURRENT-166 unless the user specifies otherwise for transaction-related tools. "
    "When suggesting actions, be proactive but respectful — e.g., 'Would you like me to help you log that transaction?' or 'Would you like me to update that for you?'"
)
)

# --- Instantiate YNAB SDK Client Once ---
client = YNABSdkClient()

# --- Tool Input Schemas and Bindings ---
class GetAccountsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_accounts(input: GetAccountsInput):
    """Get the list of accounts for a given YNAB budget."""
    logger.info(f"[TOOL] get_accounts called with budget_id={BUDGET_ID}")
    return {
        "status": "Retrieving your full budget overview...",
        "data": client.get_accounts(BUDGET_ID) 
    }

class GetBudgetDetailsInput(BaseModel):
    budget_id: str

#@budget_agent.tool_plain
#def get_budget_details(input: GetBudgetDetailsInput):
#    """Fetch detailed information about a specific budget."""
#    logger.info(f"[TOOL] get_budget_details called with budget_id={BUDGET_ID}")
#    return client.get_budget_details(BUDGET_ID)

@budget_agent.tool_plain
def get_budget_details(input: GetBudgetDetailsInput):
    logger.info(f"[TOOL] get_budget_details called with budget_id={BUDGET_ID}")
    return {
        "status": "Retrieving your full budget overview...",
        "data": client.get_budget_details(BUDGET_ID)
    }


class GetTransactionsInput(BaseModel):
    budget_id: str
    since_date: str | None = None

@budget_agent.tool_plain
def get_transactions(input: GetTransactionsInput):
    try:
        logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
        return {
            "status": "Fetching transaction history...",
            "data": client.get_transactions(BUDGET_ID, input.since_date)
        }
    except (ApiException, ProtocolError, socket.timeout, ConnectionError) as e:
        logger.warning(f"[TOOL ERROR] Network failure: {e}")
        return {
            "error": "Network issue while contacting YNAB. You can try again shortly.",
        }


#@budget_agent.tool_plain
#def get_transactions(input: GetTransactionsInput):
#    try:
#        logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
#        return client.get_transactions(BUDGET_ID, input.since_date)
#    except (ApiException, ProtocolError, socket.timeout, ConnectionError) as e:
#        logger.warning(f"[TOOL ERROR] Network failure: {e}")
#        return {
#            "error": "There was a network issue contacting the YNAB API. The remote connection was closed unexpectedly. You may try again shortly or ask to continue later."
#        }

class GetAllScheduledTransactionsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_all_scheduled_transactions(input: GetAllScheduledTransactionsInput):
    """Retrieve a list of all scheduled transactions from the budget.  Useful to see upcoming costs"""
    logger.info(f"[TOOL] get_all_scheduled_transactions called with budget_id={BUDGET_ID}")
    return {
        "status": "Checking scheduled transactions...",
        "data": client.get_scheduled_transactions(BUDGET_ID)
    }

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
    "status": "Attempt to create scheduled transaction failed.",
    "error": "YNAB rejected the scheduled transaction — the date may be out of range. Please confirm the date is no more than 7 days in the past and not more than 5 years into the future."
}
    return {
    "status": "Scheduled transaction created successfully!",
    "data": response.to_dict()
} 

class GetOverspentCategoriesInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_overspent_categories(input: GetOverspentCategoriesInput):
    """List all categories that have been overspent this month."""
    logger.info(f"[TOOL] get_overspent_categories called with budget_id={BUDGET_ID}")
    categories = client.get_categories(BUDGET_ID)
    overspent = []

    for cat_group in categories:
        for cat in cat_group.get("categories", []):
            if cat.get("activity", 0) < 0 and cat.get("balance", 0) < 0:
                overspent.append({
                    "name": cat["name"],
                    "balance_display": cat.get("balance_display"),
                    "activity_display": cat.get("activity_display"),
                })
    return {
        "status": f"Found {len(overspent)} overspent categories.",
        "data": overspent
    }


class UpdateScheduledTransactionInput(BaseModel):
    scheduled_transaction_id: str
    amount_eur: float
    memo: Optional[str] = None

@budget_agent.tool_plain
def update_scheduled_transaction(input: UpdateScheduledTransactionInput):
    """Update amount or memo for an existing scheduled transaction."""
    logger.info(f"[TOOL] update_scheduled_transaction called for ID {input.scheduled_transaction_id}")

    amount_milliunits = int(input.amount_eur * 1000)

    update_data = {
        "scheduled_transaction": {
            "amount": amount_milliunits,
            "memo": input.memo
        }
    }

    try:
        updated = client.scheduled_transactions_api.update_scheduled_transaction(BUDGET_ID, input.scheduled_transaction_id, update_data)
        return {
            "status": "Scheduled transaction updated.",
            "data": updated.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update scheduled transaction: {e}")
        return {"error": "Unable to update the scheduled transaction."}


class DeleteScheduledTransactionInput(BaseModel):
    scheduled_transaction_id: str

@budget_agent.tool_plain
def delete_scheduled_transaction(input: DeleteScheduledTransactionInput):
    """Delete an existing scheduled transaction."""
    logger.info(f"[TOOL] delete_scheduled_transaction called for ID {input.scheduled_transaction_id}")

    try:
        client.scheduled_transactions_api.delete_scheduled_transaction(BUDGET_ID, input.scheduled_transaction_id)
        return {
            "status": "Scheduled transaction deleted successfully."
        }
    except Exception as e:
        logger.error(f"Failed to delete scheduled transaction: {e}")
        return {"error": "Unable to delete the scheduled transaction."}

class CreateTransactionInput(BaseModel):
    account_id: str
    date: date
    amount_eur: float
    payee_name: Optional[str] = None
    memo: Optional[str] = None
    cleared: str = "cleared"  # or "uncleared"

@budget_agent.tool_plain
def create_transaction(input: CreateTransactionInput):
    """Log a new real-world transaction into the budget."""
    logger.info(f"[TOOL] create_transaction called for account {input.account_id} on {input.date}")

    amount_milliunits = int(input.amount_eur * 1000)

    transaction = {
        "transaction": {
            "account_id": input.account_id,
            "date": input.date.isoformat(),
            "amount": amount_milliunits,
            "payee_name": input.payee_name,
            "memo": input.memo,
            "cleared": input.cleared
        }
    }

    try:
        created = client.transactions_api.create_transaction(BUDGET_ID, transaction)
        return {
            "status": "Transaction created successfully.",
            "data": created.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return {"error": "Unable to create the transaction."}


class DeleteTransactionInput(BaseModel):
    transaction_id: str

@budget_agent.tool_plain
def delete_transaction(input: DeleteTransactionInput):
    """Delete an existing real-world transaction."""
    logger.info(f"[TOOL] delete_transaction called for transaction ID {input.transaction_id}")

    try:
        client.transactions_api.delete_transaction(BUDGET_ID, input.transaction_id)
        return {
            "status": "Transaction deleted successfully."
        }
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return {"error": "Unable to delete the transaction."}

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