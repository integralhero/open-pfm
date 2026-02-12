"""Domain models and constants for Personal Finance Management."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


CATEGORIES = [
    "Transportation", "Shopping", "Entertainment", "Food",
    "Travel", "Healthcare", "Household", "Groceries", "Misc",
]

FLOW_CATEGORIES = [
    "Income", "Traditional 401k", "Roth 401k", "Utilities", "Subscription",
]

CADENCES = [
    "daily", "weekly", "monthly", "annually",
]


class Transaction(BaseModel):
    """Represents a single transaction from the spreadsheet."""
    id: Optional[str] = None
    date: date
    name: str
    amount: float
    description: Optional[str] = None
    category: Optional[str] = None


class FetchTransactionsParams(BaseModel):
    """Parameters for fetching transactions."""
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")
    category: Optional[str] = Field(None, description="Optional category filter")


class AddTransactionParams(BaseModel):
    """Parameters for adding a new transaction."""
    date: str = Field(..., description="Transaction date in YYYY-MM-DD format")
    title: str = Field(..., description="Title/name of the transaction")
    amount: float = Field(..., description="Transaction amount (e.g., 10.00)")
    note: Optional[str] = Field(None, description="Optional short note about the transaction")
    category: str = Field(..., description="Category: one of Transportation, Shopping, Entertainment, Food, Travel, Healthcare, Household, Groceries, Misc")


class UpdateTransactionParams(BaseModel):
    """Parameters for updating an existing transaction. All fields are optional."""
    date: Optional[str] = Field(None, description="New transaction date in YYYY-MM-DD format")
    title: Optional[str] = Field(None, description="New title/name of the transaction")
    amount: Optional[float] = Field(None, description="New transaction amount (e.g., 10.00)")
    note: Optional[str] = Field(None, description="New note about the transaction")
    category: Optional[str] = Field(None, description="New category: one of Transportation, Shopping, Entertainment, Food, Travel, Healthcare, Household, Groceries, Misc")


class Account(BaseModel):
    """Represents a single asset/account from the spreadsheet."""
    id: str
    name: str
    type: str
    value: float
    last_updated: Optional[date] = None
    institution: Optional[str] = None
    notes: Optional[str] = None


class Flow(BaseModel):
    """Represents a recurring financial inflow or outflow."""
    name: str
    amount: float
    category: str
    description: Optional[str] = None
    active: bool = True
    cadence: str = "weekly"


class FetchFlowsParams(BaseModel):
    """Parameters for fetching flows."""
    category: Optional[str] = Field(None, description="Optional category filter")
    active_only: Optional[bool] = Field(None, description="Optional filter to show only active flows")


class FetchAssetsParams(BaseModel):
    """Parameters for fetching assets."""
    account_type: Optional[str] = Field(None, description="Optional account type filter")
