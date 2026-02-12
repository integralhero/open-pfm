"""Tests for delete_transaction functionality."""

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

    # Mock batchUpdate
    mock_batch_update = MagicMock()
    mock_batch_update.execute.return_value = {}
    mock_service.spreadsheets().batchUpdate.return_value = mock_batch_update

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsTransactionRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestGetSheetId:
    """Test the _get_sheet_id helper method."""

    def test_returns_correct_sheet_id(self, repo):
        """Test that _get_sheet_id returns the numeric sheetId."""
        assert repo._get_sheet_id('2025') == 111
        assert repo._get_sheet_id('2026') == 222

    def test_sheet_not_found(self, repo):
        """Test that a non-existent sheet name raises ValueError."""
        with pytest.raises(ValueError, match="Sheet '2024' not found"):
            repo._get_sheet_id('2024')

    def test_api_error(self, mock_sheets_service, repo):
        """Test that an HttpError is raised as Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().get.side_effect = http_error

        with pytest.raises(Exception, match="Error fetching sheet ID"):
            repo._get_sheet_id('2025')


class TestDeleteTransactionMethod:
    """Test the GoogleSheetsTransactionRepository.delete_transaction method."""

    def test_delete_transaction_success(self, repo):
        """Test deleting a transaction returns the deleted Transaction."""
        result = repo.delete_transaction("2025-3")

        assert isinstance(result, Transaction)
        assert result.date == date(2025, 1, 15)
        assert result.name == "Coffee Shop"
        assert result.amount == 5.50
        assert result.description == "Morning coffee"
        assert result.category == "Food"

    def test_batch_update_called_with_correct_params(self, repo, mock_sheets_service):
        """Test that batchUpdate is called with the correct deleteDimension request."""
        repo.delete_transaction("2025-3")

        mock_sheets_service.spreadsheets().batchUpdate.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            body={
                'requests': [{
                    'deleteDimension': {
                        'range': {
                            'sheetId': 111,
                            'dimension': 'ROWS',
                            'startIndex': 2,
                            'endIndex': 3,
                        }
                    }
                }]
            }
        )

    def test_invalid_id_no_dash(self, repo):
        """Test that an ID without a dash raises ValueError."""
        with pytest.raises(ValueError, match="Invalid transaction ID format"):
            repo.delete_transaction("20253")

    def test_invalid_id_non_numeric_row(self, repo):
        """Test that a non-numeric row number raises ValueError."""
        with pytest.raises(ValueError, match="Invalid row number"):
            repo.delete_transaction("2025-abc")

    def test_year_sheet_not_found(self, repo):
        """Test that a non-existent year sheet raises ValueError."""
        with pytest.raises(ValueError, match="Sheet '2024' does not exist"):
            repo.delete_transaction("2024-1")

    def test_empty_row(self, mock_sheets_service, repo):
        """Test that an empty row raises ValueError."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        with pytest.raises(ValueError, match="No transaction found"):
            repo.delete_transaction("2025-99")

    def test_api_error_on_batch_update(self, mock_sheets_service, repo):
        """Test that an HttpError on batchUpdate is raised as Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().batchUpdate.side_effect = http_error

        with pytest.raises(Exception, match="Error deleting transaction"):
            repo.delete_transaction("2025-3")


class TestDeleteTransactionTool:
    """Test the delete_transaction MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_delete_transaction_tool_is_registered(self, mock_get_repo):
        """Test that delete_transaction tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "delete_transaction" in tools

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted confirmation response."""
        mock_repo = MagicMock()
        mock_repo.delete_transaction.return_value = Transaction(
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
        tool = tools["delete_transaction"]

        result = await tool.run({"transaction_id": "2025-3"})

        result_text = result.content[0].text
        assert "deleted successfully" in result_text
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
        mock_repo.delete_transaction.side_effect = ValueError("Invalid transaction ID format")
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        tool = tools["delete_transaction"]

        with pytest.raises(ValueError, match="Validation error"):
            await tool.run({"transaction_id": "bad-id"})
