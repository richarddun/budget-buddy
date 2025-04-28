from pydantic_ai import Agent
from pydantic import BaseModel, field_validator
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai import Agent
import time
import asyncio
import os
from datetime import date, timedelta
from typing import Optional
from dotenv import load_dotenv
from ynab_sdk_client import YNABSdkClient  # your wrapper
from ynab.exceptions import ApiException, BadRequestException
from urllib3.exceptions import ProtocolError
import socket
from ynab.models import PostScheduledTransactionWrapper, SaveScheduledTransaction 
from ynab.models.patch_month_category_wrapper import PatchMonthCategoryWrapper
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

    "Default behavior assumptions:\n"
    "- Default account name is 'CURRENT-166' unless the user specifies another.\n"
    "- All transaction-related tools (create_transaction, delete_transaction, etc.) require **account_id** in **UUID format** — not the account name.\n"
    "- If you only have the account name, call get_accounts first to retrieve the correct UUID before proceeding.\n"

    "If the user asks for a budget review or mentions terms like 'review', 'overspent', 'missed payments', or 'flatline', "
    "immediately call get_budget_details to provide an overview.\n"

    "Budget summaries will include hints. Always call the matching tool to get full details if needed.\n"
    "For questions about specific expenses or transactions, use get_transactions, filtering by date if relevant.\n"
    "You have full access to the user's budget ID — there is no need to ask them for it.\n"

    "To create an expected upcoming transaction (e.g., a monthly bill, recurring charge), use create_scheduled_transaction. "
    "Supply account ID, date, and amount. Optionally include payee name or category. "
    "Scheduled transactions must have dates no more than 7 days in the past and no more than 5 years into the future. "
    "If unsure, default to the 1st of next month.\n"

    "You can get all scheduled transactions with get_all_scheduled_transactions.\n"

    "Use available tools freely and confidently. "
    "Avoid unnecessary repetition or redundant calls.\n"

    "If the user asks about overspending, overbudgeting, or mentions 'where am I overspending', call get_overspent_categories.\n"
    "If the user mentions modifying or canceling a scheduled payment, use update_scheduled_transaction or delete_scheduled_transaction as appropriate.\n"
    "If the user wants to log a real-world transaction, use create_transaction, using today's date if not otherwise specified.\n"
    "If the user wants to delete a real transaction, use delete_transaction.\n"

    'If the user mentions saving for something or setting a target goal (e.g., "save €500 for vacation"), call update_category.\n'
    'If the user mentions adjusting a monthly category budget (e.g., "increase groceries budget for May"), call update_month_category.\n'

    "When interpreting amounts, assume euros unless otherwise stated.\n"
    "If no month is specified, assume the current month.\n"

    "When suggesting actions, be proactive but respectful — e.g., 'Would you like me to help you log that transaction?' or 'Would you like me to update that for you?'\n"
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
        "data": client.slim_accounts_text(client.get_accounts(BUDGET_ID) )
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
    
    budget = client.get_budget_details(BUDGET_ID)
    name = budget.get('name', 'Unknown')
    first_month = budget.get('first_month', 'Unknown')
    last_month = budget.get('last_month', 'Unknown')
    currency = budget.get('currency_format', {}).get('iso_code', 'EUR')

    id = budget.get('id', 'Unkown')
    
    summary = (
        f"Budget Name: {name}\n"
        f"From: {first_month} to {last_month}\n"
        f"Currency: {currency}\n\n"
        "This budget contains the following account IDs :\n"
        ''.join([f"Account Name:{x['name']} - Account ID: {x['id']}, " for x in budget['accounts']])+"\n\n"
        "Detailed sections:\n"
        "- To view account balances, call `get_accounts`.\n"
        "- To view recent transactions, call `get_transactions`.\n"
        "- To view your categories and budgets, call `get_categories`.\n"
        "- To check upcoming scheduled payments, call `get_all_scheduled_transactions`.\n"
    )
    
    return {
        "status": "Here's a high-level overview of your budget.",
        "data": summary
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
            "data": client.slim_transactions_text(client.get_transactions(BUDGET_ID, input.since_date))
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
        "data": client.slim_scheduled_transactions_text(client.get_scheduled_transactions(BUDGET_ID))
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
                overspent.append(
                    f"{cat['name']}: {cat.get('balance_display', 'unknown')} spent {cat.get('activity_display', 'unknown')} (id: {cat.get('id', 'missing_id')})"
                )

    overspent_text = "\n".join(overspent) if overspent else "No categories are overspent! 🎉"

    return {
        "status": f"Found {len(overspent)} overspent categories.",
        "data": overspent_text
    }

class UpdateScheduledTransactionInput(BaseModel):
    account_id: str
    scheduled_transaction_id: str
    amount_eur: Optional[float] = None
    memo: Optional[str] = None
    var_date: Optional[date] = None

@budget_agent.tool_plain
def update_scheduled_transaction(input: UpdateScheduledTransactionInput):
    """Update amount, memo, or date for an existing scheduled transaction. Account ID (uid, not account name) is required """
    logger.info(f"[TOOL] update_scheduled_transaction called for ID {input.scheduled_transaction_id}")

    try:
        from ynab.models.put_scheduled_transaction_wrapper import PutScheduledTransactionWrapper
        from ynab.models.save_scheduled_transaction import SaveScheduledTransaction

        kwargs = {}
        if input.account_id is None:
            return {"error": "the account ID, a UID, not account name, is required"}
        kwargs['account_id'] = input.account_id
        if input.amount_eur is not None:
            kwargs['amount'] = int(input.amount_eur * 1000)

        if input.memo is not None:
            kwargs['memo'] = input.memo

        if input.var_date is not None:
            if input.var_date > date.today() + timedelta(days=5*365):
                return {
                    "error": "Scheduled transaction date must be within 5 years from today."
                }
            kwargs['var_date'] = input.var_date.isoformat()

        if not kwargs:
            return {"error": "No fields provided to update. Specify amount, memo, or date."}

        update_detail = SaveScheduledTransaction(**kwargs)
        wrapper = PutScheduledTransactionWrapper(scheduled_transaction=update_detail)

        updated = client.scheduled_transactions_api.update_scheduled_transaction(
            BUDGET_ID,
            input.scheduled_transaction_id,
            wrapper
        )

        return {
            "status": "Scheduled transaction updated successfully.",
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
    """Log a new real-world transaction into the budget. Requires account_id UUID, not account name."""
    logger.info(f"[TOOL] create_transaction called for account {input.account_id} on {input.date}")

    # 🔥 Validate and auto-fix account_id if needed
    if "-" not in input.account_id:
        logger.warning("[TOOL] Provided account_id does not look like a UUID. Attempting lookup...")
        accounts = client.get_accounts(BUDGET_ID)
        matching_account = next((acct for acct in accounts if acct["name"] == input.account_id), None)
        if matching_account:
            input.account_id = matching_account["id"]
            logger.info(f"[TOOL] Matched account name to UUID: {input.account_id}")
        else:
            logger.error(f"[TOOL ERROR] No account found matching name {input.account_id}")
            return {"error": f"No account found matching name {input.account_id}. Please check your account names."}

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

class GetCategoriesInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_categories(input: GetCategoriesInput):
    """Retrieve all categories grouped by their group name."""
    logger.info(f"[TOOL] get_categories called with budget_id={BUDGET_ID}")
    return {
        "status": "Fetching list of categories...",
        "data": client.slim_categories_text(client.get_categories(BUDGET_ID))
    }

class GetCategoryByIdInput(BaseModel):
    budget_id: str
    category_id: str

@budget_agent.tool_plain
def get_category_by_id(input: GetCategoryByIdInput):
    """Fetch details for a single category."""
    logger.info(f"[TOOL] get_category_by_id called with category_id={input.category_id}")
    return {
        "status": f"Retrieving category {input.category_id}...",
        "data": client.get_category_by_id(BUDGET_ID, input.category_id)
    }


class UpdateCategoryInput(BaseModel):
    category_id: str
    budgeted_amount_eur: float
    goal_type: Optional[str] = None  # e.g., "TB", "TBD", "MF", "NEED"
    goal_target: Optional[float] = None  # Amount in euros

@budget_agent.tool_plain
def update_category(input: UpdateCategoryInput):
    """Update the target or type of a category (e.g., setting a savings goal)."""
    logger.info(f"[TOOL] update_category called for {input.category_id}")

    data = {
        "category": {
               "budgeted": int(input.budgeted_amount_eur * 1000)  # Convert to milliunits
        }
    }

    if input.goal_type:
        data["category"]["goal_type"] = input.goal_type
    if input.goal_target is not None:
        # Convert euros to milliunits
        data["category"]["goal_target"] = int(input.goal_target * 1000)

    try:
        response = client.update_category(BUDGET_ID, input.category_id, data)
        return {
            "status": "Category updated successfully!",
            "data": response.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update category: {e}")
        return {"error": "Unable to update the category."}


class UpdateMonthCategoryInput(BaseModel):
    category_id: str
    month: date
    budgeted_amount_eur: float

@budget_agent.tool_plain
def update_month_category(input: UpdateMonthCategoryInput):
    """Adjust the budgeted amount for a specific month and category."""
    logger.info(f"[TOOL] update_month_category called for {input.category_id} in month {input.month}")

    data = {
        "category": {
            "budgeted": int(input.budgeted_amount_eur * 1000)  # Convert to milliunits
        }
    }

    try:
        response = client.update_month_category(BUDGET_ID, input.month.isoformat(), input.category_id, data)
        return {
            "status": "Monthly category budget updated successfully!",
            "data": response.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update month category: {e}")
        return {"error": "Unable to update the monthly budgeted amount."}

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