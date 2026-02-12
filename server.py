#!/usr/bin/env python3
"""
FastMCP Server for Personal Finance Management
Fetches transactions from Google Spreadsheets using FastMCP
"""

import hmac
import os
from datetime import datetime
from typing import Optional

from fastmcp import FastMCP
from pydantic import Field

from google_sheets_auth import create_sheets_service
from models import (
    CATEGORIES,
    Account,
    AddTransactionParams,
    FetchAssetsParams,
    FetchFlowsParams,
    FetchTransactionsParams,
    Flow,
    Transaction,
    UpdateTransactionParams,
)
from repository import (
    AccountRepository,
    FlowRepository,
    GoogleSheetsAccountRepository,
    GoogleSheetsFlowRepository,
    GoogleSheetsTransactionRepository,
    TransactionRepository,
)

# Server transport configuration
TRANSPORT = os.getenv('MCP_TRANSPORT', 'stdio')
HOST = os.getenv('MCP_HOST', '0.0.0.0')
PORT = int(os.getenv('MCP_PORT', '') or os.getenv('PORT', '8000'))
MCP_AUTH_TOKEN = os.getenv('MCP_AUTH_TOKEN', '')
# FastMCP 2.x deprecated SSE in favour of Streamable HTTP ("http").
# Normalise the legacy "sse" value so existing deployments keep working.
_TRANSPORT_ALIASES = {"sse": "http"}


class _BearerAuthMiddleware:
    """ASGI middleware that requires a valid Bearer token on every HTTP request."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_value = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(auth_value, f"Bearer {self.token}"):
                from starlette.responses import Response
                response = Response("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# Global repository instances
_repository: TransactionRepository | None = None
_account_repository: AccountRepository | None = None
_flow_repository: FlowRepository | None = None


def get_repository() -> TransactionRepository:
    """Get or create the transaction repository instance."""
    global _repository
    if _repository is None:
        service = create_sheets_service()
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '')
        _repository = GoogleSheetsTransactionRepository(service, spreadsheet_id)
    return _repository


def get_account_repository() -> AccountRepository:
    """Get or create the account repository instance."""
    global _account_repository
    if _account_repository is None:
        service = create_sheets_service()
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '')
        _account_repository = GoogleSheetsAccountRepository(service, spreadsheet_id)
    return _account_repository


def get_flow_repository() -> FlowRepository:
    """Get or create the flow repository instance."""
    global _flow_repository
    if _flow_repository is None:
        service = create_sheets_service()
        spreadsheet_id = os.getenv('GOOGLE_SPREADSHEET_ID', '')
        _flow_repository = GoogleSheetsFlowRepository(service, spreadsheet_id)
    return _flow_repository


# Create FastMCP app
app = FastMCP("pfm-mcp")


@app.tool()
async def fetch_transactions(
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Field(..., description="End date in YYYY-MM-DD format"),
    category: Optional[str] = Field(None, description="Optional category filter"),
) -> str:
    """
    Fetch transactions from Google Spreadsheet within a date range with optional category filtering.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        category: Optional category to filter by

    Returns:
        Formatted string with transaction data
    """
    try:
        params = FetchTransactionsParams(
            start_date=start_date,
            end_date=end_date,
            category=category,
        )

        start_date_obj = datetime.strptime(params.start_date, '%Y-%m-%d').date()
        end_date_obj = datetime.strptime(params.end_date, '%Y-%m-%d').date()

        if start_date_obj > end_date_obj:
            raise ValueError("Start date must be before or equal to end date")

        repo = get_repository()
        transactions = repo.fetch_transactions(
            start_date=start_date_obj,
            end_date=end_date_obj,
            category_filter=params.category,
        )

        transaction_data = [
            {
                "date": t.date.isoformat(),
                "name": t.name,
                "amount": t.amount,
                "description": t.description,
                "category": t.category,
            }
            for t in transactions
        ]

        return (
            f"Found {len(transaction_data)} transactions from {params.start_date} to {params.end_date}"
            + (f" in category '{params.category}'" if params.category else "")
            + f"\n\n{str(transaction_data)}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error fetching transactions: {str(e)}")


@app.tool()
async def get_transaction(
    transaction_id: str = Field(..., description="Transaction ID in '{year}-{row}' format (e.g., '2025-42')"),
) -> str:
    """
    Fetch a single transaction by its ID.

    The transaction ID is a combination of the year (sheet name) and row number,
    formatted as '{year}-{row}'. For example, '2025-42' refers to row 42 in the
    2025 sheet.

    Args:
        transaction_id: Transaction ID in '{year}-{row}' format

    Returns:
        Formatted string with the transaction details
    """
    try:
        repo = get_repository()
        transaction = repo.get_transaction(transaction_id)

        return (
            f"Transaction {transaction.id}\n\n"
            f"Date: {transaction.date.isoformat()}\n"
            f"Name: {transaction.name}\n"
            f"Amount: ${transaction.amount:.2f}\n"
            f"Description: {transaction.description or 'N/A'}\n"
            f"Category: {transaction.category or 'N/A'}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error fetching transaction: {str(e)}")


@app.tool()
async def add_transaction(
    date: str = Field(..., description="Transaction date in YYYY-MM-DD format"),
    title: str = Field(..., description="Title/name of the transaction"),
    amount: float = Field(..., description="Transaction amount (e.g., 10.00 for $10.00)"),
    category: str = Field(..., description="Category: one of Transportation, Shopping, Entertainment, Food, Travel, Healthcare, Household, Groceries, Misc"),
    note: Optional[str] = Field(None, description="Optional short note about the transaction"),
) -> str:
    """
    Add a new transaction to the Google Spreadsheet.

    The transaction will be added to the sheet corresponding to the year of the date.
    For example, a transaction dated 2026-01-15 will be added to the "2026" sheet.

    Args:
        date: Transaction date in YYYY-MM-DD format
        title: Title/name of the transaction
        amount: Transaction amount (positive number, e.g., 10.00)
        category: Category from: Transportation, Shopping, Entertainment, Food, Travel, Healthcare, Household, Groceries, Misc
        note: Optional note/description for the transaction

    Returns:
        Formatted string confirming the transaction was added
    """
    try:
        params = AddTransactionParams(
            date=date,
            title=title,
            amount=amount,
            category=category,
            note=note,
        )

        if params.category not in CATEGORIES:
            raise ValueError(
                f"Invalid category '{params.category}'. Must be one of: {', '.join(CATEGORIES)}"
            )

        transaction_date = datetime.strptime(params.date, '%Y-%m-%d').date()

        txn = Transaction(
            date=transaction_date,
            name=params.title,
            amount=params.amount,
            description=params.note,
            category=params.category,
        )

        repo = get_repository()
        result = repo.add_transaction(txn)

        return (
            f"Transaction added successfully to sheet '{result.date.year}'\n\n"
            f"Date: {result.date.strftime('%m/%d/%Y')}\n"
            f"Title: {result.name}\n"
            f"Amount: ${result.amount:.2f}\n"
            f"Note: {result.description or 'N/A'}\n"
            f"Category: {result.category}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error adding transaction: {str(e)}")


@app.tool()
async def delete_transaction(
    transaction_id: str = Field(..., description="Transaction ID in '{year}-{row}' format (e.g., '2025-42')"),
) -> str:
    """
    Delete a transaction by its ID.

    The transaction ID is a combination of the year (sheet name) and row number,
    formatted as '{year}-{row}'. For example, '2025-42' refers to row 42 in the
    2025 sheet. The row is permanently removed from the spreadsheet.

    Args:
        transaction_id: Transaction ID in '{year}-{row}' format

    Returns:
        Formatted string confirming the deleted transaction's details
    """
    try:
        repo = get_repository()
        transaction = repo.delete_transaction(transaction_id)

        return (
            f"Transaction {transaction_id} deleted successfully\n\n"
            f"Date: {transaction.date.isoformat()}\n"
            f"Name: {transaction.name}\n"
            f"Amount: ${transaction.amount:.2f}\n"
            f"Description: {transaction.description or 'N/A'}\n"
            f"Category: {transaction.category or 'N/A'}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error deleting transaction: {str(e)}")


@app.tool()
async def update_transaction(
    transaction_id: str = Field(..., description="Transaction ID in '{year}-{row}' format (e.g., '2025-42')"),
    date: Optional[str] = Field(None, description="New transaction date in YYYY-MM-DD format"),
    title: Optional[str] = Field(None, description="New title/name of the transaction"),
    amount: Optional[float] = Field(None, description="New transaction amount (e.g., 10.00 for $10.00)"),
    category: Optional[str] = Field(None, description="New category: one of Transportation, Shopping, Entertainment, Food, Travel, Healthcare, Household, Groceries, Misc"),
    note: Optional[str] = Field(None, description="New note about the transaction"),
) -> str:
    """
    Update an existing transaction by its ID.

    The transaction ID is a combination of the year (sheet name) and row number,
    formatted as '{year}-{row}'. For example, '2025-42' refers to row 42 in the
    2025 sheet.

    Only the fields you provide will be updated; the rest keep their current values.
    The date cannot be changed to a different year than the transaction's sheet.

    Args:
        transaction_id: Transaction ID in '{year}-{row}' format
        date: New date in YYYY-MM-DD format (must stay in same year)
        title: New title/name
        amount: New amount
        category: New category (must be a valid category)
        note: New note/description

    Returns:
        Formatted string with the updated transaction details
    """
    try:
        params = UpdateTransactionParams(
            date=date,
            title=title,
            amount=amount,
            category=category,
            note=note,
        )

        if params.category is not None and params.category not in CATEGORIES:
            raise ValueError(
                f"Invalid category '{params.category}'. Must be one of: {', '.join(CATEGORIES)}"
            )

        parsed_date = None
        if params.date is not None:
            parsed_date = datetime.strptime(params.date, '%Y-%m-%d').date()

        repo = get_repository()
        updated = repo.update_transaction(
            transaction_id=transaction_id,
            date=parsed_date,
            name=params.title,
            amount=params.amount,
            description=params.note,
            category=params.category,
        )

        return (
            f"Transaction {transaction_id} updated successfully\n\n"
            f"Date: {updated.date.isoformat()}\n"
            f"Name: {updated.name}\n"
            f"Amount: ${updated.amount:.2f}\n"
            f"Description: {updated.description or 'N/A'}\n"
            f"Category: {updated.category or 'N/A'}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error updating transaction: {str(e)}")


@app.tool()
async def fetch_assets(
    account_type: Optional[str] = Field(None, description="Optional account type filter (e.g., 'checking', 'savings', 'investment')"),
) -> str:
    """
    Fetch assets/accounts from the Assets sheet in the Google Spreadsheet.

    Returns all assets, optionally filtered by account type. Each asset has an id,
    name, type, value, last_updated date, institution, and notes.

    Args:
        account_type: Optional type to filter by (case-insensitive)

    Returns:
        Formatted string with asset data
    """
    try:
        params = FetchAssetsParams(account_type=account_type)

        repo = get_account_repository()
        accounts = repo.fetch_accounts(account_type=params.account_type)

        account_data = [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "value": a.value,
                "last_updated": a.last_updated.isoformat() if a.last_updated else None,
                "institution": a.institution,
                "notes": a.notes,
            }
            for a in accounts
        ]

        return (
            f"Found {len(account_data)} assets"
            + (f" of type '{params.account_type}'" if params.account_type else "")
            + f"\n\n{str(account_data)}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error fetching assets: {str(e)}")


@app.tool()
async def fetch_flows(
    category: Optional[str] = Field(None, description="Optional category filter (e.g., 'Income', 'Utilities')"),
    active_only: Optional[bool] = Field(None, description="Optional filter: True for active flows only, False for inactive only"),
) -> str:
    """
    Fetch recurring financial flows (inflows and outflows) from the Recurring sheet.

    Each flow has a name, amount (positive for inflows, negative for outflows),
    category, description, active status, and cadence.

    Args:
        category: Optional category to filter by (case-insensitive)
        active_only: Optional filter by active status

    Returns:
        Formatted string with flow data
    """
    try:
        params = FetchFlowsParams(category=category, active_only=active_only)

        repo = get_flow_repository()
        flows = repo.fetch_flows(
            category=params.category,
            active_only=params.active_only,
        )

        flow_data = [
            {
                "name": f.name,
                "amount": f.amount,
                "category": f.category,
                "description": f.description,
                "active": f.active,
                "cadence": f.cadence,
            }
            for f in flows
        ]

        return (
            f"Found {len(flow_data)} flows"
            + (f" in category '{params.category}'" if params.category else "")
            + (f" (active only)" if params.active_only is True else "")
            + (f" (inactive only)" if params.active_only is False else "")
            + f"\n\n{str(flow_data)}"
        )

    except ValueError as e:
        raise ValueError(f"Validation error: {str(e)}")
    except Exception as e:
        raise Exception(f"Error fetching flows: {str(e)}")


if __name__ == "__main__":
    resolved = _TRANSPORT_ALIASES.get(TRANSPORT, TRANSPORT)
    if resolved == "http":
        middleware = []
        if MCP_AUTH_TOKEN:
            from starlette.middleware import Middleware
            middleware.append(Middleware(_BearerAuthMiddleware, token=MCP_AUTH_TOKEN))
        app.run(transport="http", host=HOST, port=PORT, middleware=middleware)
    else:
        app.run()
