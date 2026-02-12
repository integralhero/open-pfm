"""Tests for get_transaction functionality."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

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

    # Mock the spreadsheets().values().get() call with a single row
    mock_values_get = MagicMock()
    mock_values_get.execute.return_value = {
        'values': [
            ['01/15/2025', 'Coffee Shop', '$5.50', 'Morning coffee', 'Food'],
        ]
    }
    mock_service.spreadsheets().values().get.return_value = mock_values_get

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsTransactionRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestGetTransactionMethod:
    """Test the GoogleSheetsTransactionRepository.get_transaction method."""

    def test_get_transaction_success(self, repo):
        """Test fetching a single transaction by valid ID."""
        result = repo.get_transaction("2025-3")

        assert isinstance(result, Transaction)
        assert result.date == date(2025, 1, 15)
        assert result.name == "Coffee Shop"
        assert result.amount == 5.50
        assert result.description == "Morning coffee"
        assert result.category == "Food"

    def test_transaction_id_is_set(self, repo):
        """Test that the returned transaction has its id field set."""
        result = repo.get_transaction("2025-3")

        assert result.id == "2025-3"

    def test_invalid_id_no_dash(self, repo):
        """Test that an ID without a dash raises ValueError."""
        with pytest.raises(ValueError, match="Invalid transaction ID format"):
            repo.get_transaction("20253")

    def test_invalid_id_multiple_dashes(self, repo):
        """Test that an ID with multiple dashes raises ValueError."""
        with pytest.raises(ValueError, match="Invalid transaction ID format"):
            repo.get_transaction("2025-3-1")

    def test_invalid_id_non_numeric_row(self, repo):
        """Test that a non-numeric row number raises ValueError."""
        with pytest.raises(ValueError, match="Invalid row number"):
            repo.get_transaction("2025-abc")

    def test_invalid_id_non_numeric_year(self, repo):
        """Test that a non-numeric year raises ValueError."""
        with pytest.raises(ValueError, match="Invalid year"):
            repo.get_transaction("abc-3")

    def test_row_number_zero(self, repo):
        """Test that row number 0 raises ValueError."""
        with pytest.raises(ValueError, match="Row number must be positive"):
            repo.get_transaction("2025-0")

    def test_row_number_negative(self, repo):
        """Test that a negative row number raises ValueError (caught as invalid format due to extra dash)."""
        with pytest.raises(ValueError, match="Invalid transaction ID format"):
            repo.get_transaction("2025--1")

    def test_year_sheet_not_found(self, repo):
        """Test that a non-existent year sheet raises ValueError."""
        with pytest.raises(ValueError, match="Sheet '2024' does not exist"):
            repo.get_transaction("2024-1")

    def test_empty_row(self, mock_sheets_service, repo):
        """Test that an empty row raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="No transaction found"):
            repo.get_transaction("2025-99")

    def test_no_values_key(self, mock_sheets_service, repo):
        """Test that a response with no 'values' key raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="No transaction found"):
            repo.get_transaction("2025-99")

    def test_row_too_short(self, mock_sheets_service, repo):
        """Test that a row with fewer than 3 columns raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['01/15/2025', 'Only Two']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="Could not parse transaction"):
            repo.get_transaction("2025-1")

    def test_unparseable_date(self, mock_sheets_service, repo):
        """Test that a row with an unparseable date raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['not-a-date', 'Bad Row', '$10.00', 'Note', 'Food']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="Could not parse transaction"):
            repo.get_transaction("2025-1")

    def test_api_called_with_correct_range(self, repo, mock_sheets_service):
        """Test that the API is called with the correct single-row range."""
        repo.get_transaction("2025-42")

        mock_sheets_service.spreadsheets().values().get.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            range="'2025'!A42:E42",
        )

    def test_optional_fields_missing(self, mock_sheets_service, repo):
        """Test rows with 3-4 columns populate description/category as None."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['01/15/2025', 'No Extras', '$5.00']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.description is None
        assert result.category is None

    def test_description_only(self, mock_sheets_service, repo):
        """Test row with description but no category."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['01/15/2025', 'Has Desc', '$5.00', 'A note']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.description == "A note"
        assert result.category is None

    def test_amount_parsing_dollar_sign(self, mock_sheets_service, repo):
        """Test that amounts with $ are parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['01/15/2025', 'Test', '$1,234.56', 'Note', 'Food']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.amount == 1234.56

    def test_amount_parsing_plain_number(self, mock_sheets_service, repo):
        """Test that plain numeric amounts are parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['01/15/2025', 'Test', '42.00', 'Note', 'Food']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.amount == 42.00

    def test_date_format_yyyy_mm_dd(self, mock_sheets_service, repo):
        """Test that YYYY-MM-DD date format is parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['2025-06-20', 'Test', '$10.00', 'Note', 'Food']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.date == date(2025, 6, 20)

    def test_date_format_mm_dd_yy(self, mock_sheets_service, repo):
        """Test that MM/DD/YY date format is parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [['09/10/25', 'Test', '$15.00', 'Note', 'Food']]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        result = repo.get_transaction("2025-1")

        assert result.date == date(2025, 9, 10)

    def test_http_error_raises_exception(self, mock_sheets_service, repo):
        """Test that an HttpError from the API is raised as an Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().values().get.side_effect = http_error

        with pytest.raises(Exception, match="Error fetching transaction"):
            repo.get_transaction("2025-1")


class TestGetTransactionTool:
    """Test the get_transaction MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_get_transaction_tool_is_registered(self, mock_get_repo):
        """Test that get_transaction tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "get_transaction" in tools

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted response string."""
        mock_repo = MagicMock()
        mock_repo.get_transaction.return_value = Transaction(
            id="2025-3",
            date=date(2025, 1, 15),
            name="Coffee Shop",
            amount=5.50,
            description="Morning coffee",
            category="Food",
        )
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["get_transaction"]

        result = await tool.run({"transaction_id": "2025-3"})

        result_text = result.content[0].text
        assert "Transaction 2025-3" in result_text
        assert "Coffee Shop" in result_text
        assert "$5.50" in result_text
        assert "Morning coffee" in result_text
        assert "Food" in result_text

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_invalid_id_raises_value_error(self, mock_get_repo):
        """Test that an invalid transaction ID raises ValueError."""
        mock_repo = MagicMock()
        mock_repo.get_transaction.side_effect = ValueError("Invalid transaction ID format")
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["get_transaction"]

        with pytest.raises(ValueError, match="Validation error"):
            await tool.run({"transaction_id": "bad-id"})
