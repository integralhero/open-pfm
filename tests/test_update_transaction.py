"""Tests for update_transaction functionality."""

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

    # Mock the spreadsheets().get() call for getting sheet names and IDs
    mock_get = MagicMock()
    mock_get.execute.return_value = {
        'sheets': [
            {'properties': {'title': '2025', 'sheetId': 111}},
            {'properties': {'title': '2026', 'sheetId': 222}},
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

    # Mock values().update()
    mock_values_update = MagicMock()
    mock_values_update.execute.return_value = {}
    mock_service.spreadsheets().values().update.return_value = mock_values_update

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsTransactionRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestUpdateTransactionMethod:
    """Test the GoogleSheetsTransactionRepository.update_transaction method."""

    def test_update_name_only(self, repo):
        """Test updating just the name keeps other fields unchanged."""
        result = repo.update_transaction("2025-3", name="Starbucks")

        assert isinstance(result, Transaction)
        assert result.id == "2025-3"
        assert result.name == "Starbucks"
        # Unchanged fields
        assert result.date == date(2025, 1, 15)
        assert result.amount == 5.50
        assert result.description == "Morning coffee"
        assert result.category == "Food"

    def test_update_amount_only(self, repo):
        """Test updating just the amount."""
        result = repo.update_transaction("2025-3", amount=12.99)

        assert result.amount == 12.99
        assert result.name == "Coffee Shop"

    def test_update_category_only(self, repo):
        """Test updating just the category."""
        result = repo.update_transaction("2025-3", category="Entertainment")

        assert result.category == "Entertainment"
        assert result.name == "Coffee Shop"

    def test_update_date_same_year(self, repo):
        """Test updating the date within the same year."""
        result = repo.update_transaction("2025-3", date=date(2025, 6, 20))

        assert result.date == date(2025, 6, 20)
        assert result.name == "Coffee Shop"

    def test_update_description(self, repo):
        """Test updating the description/note."""
        result = repo.update_transaction("2025-3", description="Afternoon latte")

        assert result.description == "Afternoon latte"

    def test_update_multiple_fields(self, repo):
        """Test updating multiple fields at once."""
        result = repo.update_transaction(
            "2025-3",
            name="Tea House",
            amount=3.75,
            category="Entertainment",
        )

        assert result.name == "Tea House"
        assert result.amount == 3.75
        assert result.category == "Entertainment"
        # Unchanged
        assert result.date == date(2025, 1, 15)
        assert result.description == "Morning coffee"

    def test_values_update_called_with_correct_params(self, repo, mock_sheets_service):
        """Test that values().update() is called with the correct range and body."""
        repo.update_transaction("2025-3", name="Starbucks")

        mock_sheets_service.spreadsheets().values().update.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            range="'2025'!A3:E3",
            valueInputOption='USER_ENTERED',
            body={'values': [['01/15/2025', 'Starbucks', '$5.50', 'Morning coffee', 'Food']]},
        )

    def test_cross_year_date_raises_error(self, repo):
        """Test that changing the date to a different year raises ValueError."""
        with pytest.raises(ValueError, match="Cannot change date to a different year"):
            repo.update_transaction("2025-3", date=date(2026, 1, 15))

    def test_invalid_id_no_dash(self, repo):
        """Test that an ID without a dash raises ValueError."""
        with pytest.raises(ValueError, match="Invalid transaction ID format"):
            repo.update_transaction("20253", name="Test")

    def test_invalid_id_non_numeric_row(self, repo):
        """Test that a non-numeric row number raises ValueError."""
        with pytest.raises(ValueError, match="Invalid row number"):
            repo.update_transaction("2025-abc", name="Test")

    def test_year_sheet_not_found(self, repo):
        """Test that a non-existent year sheet raises ValueError."""
        with pytest.raises(ValueError, match="Sheet '2024' does not exist"):
            repo.update_transaction("2024-1", name="Test")

    def test_empty_row(self, mock_sheets_service, repo):
        """Test that an empty row raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="No transaction found"):
            repo.update_transaction("2025-99", name="Test")

    def test_api_error_on_update(self, mock_sheets_service, repo):
        """Test that an HttpError on values().update() is raised as Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().values().update.side_effect = http_error

        with pytest.raises(Exception, match="Error updating transaction"):
            repo.update_transaction("2025-3", name="Test")


class TestUpdateTransactionTool:
    """Test the update_transaction MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_update_transaction_tool_is_registered(self, mock_get_repo):
        """Test that update_transaction tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "update_transaction" in tools

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted confirmation response."""
        mock_repo = MagicMock()
        mock_repo.update_transaction.return_value = Transaction(
            id="2025-3",
            date=date(2025, 1, 15),
            name="Starbucks",
            amount=5.50,
            description="Morning coffee",
            category="Food",
        )
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["update_transaction"]

        result = await tool.run({
            "transaction_id": "2025-3",
            "title": "Starbucks",
        })

        result_text = result.content[0].text
        assert "updated successfully" in result_text
        assert "Starbucks" in result_text
        assert "$5.50" in result_text
        assert "Morning coffee" in result_text
        assert "Food" in result_text

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_invalid_category_raises_value_error(self, mock_get_repo):
        """Test that an invalid category raises ValueError before hitting the repo."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        tool = tools["update_transaction"]

        with pytest.raises(ValueError, match="Invalid category"):
            await tool.run({
                "transaction_id": "2025-3",
                "category": "InvalidCategory",
            })

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_invalid_id_raises_value_error(self, mock_get_repo):
        """Test that an invalid transaction ID raises ValueError."""
        mock_repo = MagicMock()
        mock_repo.update_transaction.side_effect = ValueError("Invalid transaction ID format")
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["update_transaction"]

        with pytest.raises(ValueError, match="Validation error"):
            await tool.run({
                "transaction_id": "bad-id",
                "title": "Test",
            })

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_passes_none_for_omitted_fields(self, mock_get_repo):
        """Test that omitted fields are passed as None to the repository."""
        mock_repo = MagicMock()
        mock_repo.update_transaction.return_value = Transaction(
            id="2025-3",
            date=date(2025, 1, 15),
            name="Updated",
            amount=5.50,
            description=None,
            category=None,
        )
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["update_transaction"]

        await tool.run({
            "transaction_id": "2025-3",
            "title": "Updated",
        })

        mock_repo.update_transaction.assert_called_once_with(
            transaction_id="2025-3",
            date=None,
            name="Updated",
            amount=None,
            description=None,
            category=None,
        )
