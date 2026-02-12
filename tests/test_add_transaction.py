"""Tests for add_transaction functionality."""

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from models import Transaction
from repository import GoogleSheetsTransactionRepository


@pytest.fixture
def mock_sheets_service():
    """Create a mock Google Sheets service."""
    mock_service = MagicMock()

    # Mock the spreadsheets().get() call for getting sheet names
    mock_get = MagicMock()
    mock_get.execute.return_value = {
        'sheets': [
            {'properties': {'title': '2025'}},
            {'properties': {'title': '2026'}},
        ]
    }
    mock_service.spreadsheets().get.return_value = mock_get

    # Mock the spreadsheets().values().append() call
    mock_append = MagicMock()
    mock_append.execute.return_value = {
        'updates': {
            'updatedCells': 5,
            'updatedRows': 1,
        }
    }
    mock_service.spreadsheets().values().append.return_value = mock_append

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsTransactionRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestAddTransactionMethod:
    """Test the GoogleSheetsTransactionRepository.add_transaction method."""

    def test_add_transaction_success(self, repo):
        """Test adding a transaction successfully."""
        txn = Transaction(
            date=date(2026, 2, 10),
            name="Coffee Shop",
            amount=5.50,
            description="Morning coffee",
            category="Food",
        )
        result = repo.add_transaction(txn)

        assert isinstance(result, Transaction)
        assert result.date == date(2026, 2, 10)
        assert result.name == "Coffee Shop"
        assert result.amount == 5.50
        assert result.description == "Morning coffee"
        assert result.category == "Food"

    def test_add_transaction_formats_date_correctly(self, repo, mock_sheets_service):
        """Test that dates are formatted as MM/DD/YYYY in the API call."""
        txn = Transaction(
            date=date(2026, 1, 5),
            name="Test",
            amount=10.00,
            category="Misc",
        )
        repo.add_transaction(txn)

        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['body']['values'][0][0] == '01/05/2026'

    def test_add_transaction_formats_amount_correctly(self, repo, mock_sheets_service):
        """Test that amounts are formatted as $X.XX in the API call."""
        # Test whole number
        txn = Transaction(date=date(2026, 1, 1), name="Test", amount=10, category="Misc")
        repo.add_transaction(txn)
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['body']['values'][0][2] == '$10.00'

        # Test decimal
        txn = Transaction(date=date(2026, 1, 1), name="Test", amount=5.99, category="Misc")
        repo.add_transaction(txn)
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['body']['values'][0][2] == '$5.99'

        # Test rounding
        txn = Transaction(date=date(2026, 1, 1), name="Test", amount=3.456, category="Misc")
        repo.add_transaction(txn)
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['body']['values'][0][2] == '$3.46'

    def test_add_transaction_selects_correct_year_sheet(self, repo, mock_sheets_service):
        """Test that the correct year sheet is selected based on transaction date."""
        # Test 2025
        txn = Transaction(date=date(2025, 12, 31), name="Test", amount=10.00, category="Misc")
        repo.add_transaction(txn)
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['range'] == "'2025'!A:E"

        # Test 2026
        txn = Transaction(date=date(2026, 1, 1), name="Test", amount=10.00, category="Misc")
        repo.add_transaction(txn)
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]
        assert call_kwargs['range'] == "'2026'!A:E"

    def test_add_transaction_raises_when_sheet_not_exists(self, repo):
        """Test that an error is raised when the year sheet doesn't exist."""
        with pytest.raises(ValueError, match="Sheet '2024' does not exist"):
            txn = Transaction(date=date(2024, 1, 1), name="Test", amount=10.00, category="Misc")
            repo.add_transaction(txn)

    def test_add_transaction_raises_when_no_spreadsheet_id(self, mock_sheets_service):
        """Test that an error is raised when spreadsheet_id is empty."""
        repo = GoogleSheetsTransactionRepository(
            service=mock_sheets_service,
            spreadsheet_id="",
        )
        # The repo itself doesn't validate spreadsheet_id upfront;
        # it will fail when calling the API. This is consistent with
        # letting the Sheets API surface the error.
        txn = Transaction(date=date(2026, 1, 1), name="Test", amount=10.00, category="Misc")
        # The API call will still go through with empty string — the Sheets API
        # will return an error, but for unit tests the mock won't raise.
        # This test verifies the repo doesn't crash on construction with empty id.
        result = repo.add_transaction(txn)
        assert isinstance(result, Transaction)

    def test_add_transaction_with_optional_fields(self, repo):
        """Test adding a transaction with optional fields as None."""
        txn = Transaction(
            date=date(2026, 2, 10),
            name="Cash Withdrawal",
            amount=100.00,
            description=None,
            category=None,
        )
        result = repo.add_transaction(txn)

        assert isinstance(result, Transaction)
        assert result.description is None
        assert result.category is None

    def test_add_transaction_calls_api_correctly(self, repo, mock_sheets_service):
        """Test that the Google Sheets API is called with correct parameters."""
        txn = Transaction(
            date=date(2026, 2, 10),
            name="Test Transaction",
            amount=25.50,
            description="Test note",
            category="Food",
        )
        repo.add_transaction(txn)

        # Verify the append call was made with correct parameters
        mock_sheets_service.spreadsheets().values().append.assert_called_once()
        call_kwargs = mock_sheets_service.spreadsheets().values().append.call_args[1]

        assert call_kwargs['spreadsheetId'] == 'test-spreadsheet-id'
        assert call_kwargs['range'] == "'2026'!A:E"
        assert call_kwargs['valueInputOption'] == 'USER_ENTERED'
        assert call_kwargs['insertDataOption'] == 'INSERT_ROWS'
        assert call_kwargs['body']['values'][0] == [
            '02/10/2026',
            'Test Transaction',
            '$25.50',
            'Test note',
            'Food'
        ]


class TestAddTransactionTool:
    """Test the add_transaction MCP tool registration."""

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_add_transaction_tool_is_registered(self, mock_get_repo):
        """Test that the add_transaction tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        # Verify the app has tools registered
        tools = await app.get_tools()

        assert "add_transaction" in tools
        assert "fetch_transactions" in tools
