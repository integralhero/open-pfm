"""Tests for fetch_assets functionality."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from models import Account
from repository import GoogleSheetsAccountRepository


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
            {'properties': {'title': 'Assets'}},
        ]
    }
    mock_service.spreadsheets().get.return_value = mock_get

    # Mock the spreadsheets().values().get() call with default data
    mock_values_get = MagicMock()
    mock_values_get.execute.return_value = {
        'values': [
            ['1', 'Main Checking', 'checking', '$5,000.00', '01/15/2025', 'Chase', 'Primary account'],
            ['2', 'Savings', 'savings', '$25,000.00', '02/01/2025', 'Ally Bank', 'Emergency fund'],
            ['3', 'Brokerage', 'investment', '$150,000.00', '03/10/2025', 'Fidelity', ''],
        ]
    }
    mock_service.spreadsheets().values().get.return_value = mock_values_get

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsAccountRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestFetchAccountsMethod:
    """Test the GoogleSheetsAccountRepository.fetch_accounts method."""

    def test_fetch_accounts_success(self, repo):
        """Test fetching all accounts returns correct results."""
        results = repo.fetch_accounts()

        assert len(results) == 3
        assert results[0].id == "1"
        assert results[0].name == "Main Checking"
        assert results[0].type == "checking"
        assert results[0].value == 5000.00
        assert results[0].last_updated == date(2025, 1, 15)
        assert results[0].institution == "Chase"
        assert results[0].notes == "Primary account"

    def test_fetch_accounts_type_filter(self, repo):
        """Test that type filtering is case-insensitive."""
        results = repo.fetch_accounts(account_type="CHECKING")

        assert len(results) == 1
        assert results[0].type == "checking"
        assert results[0].name == "Main Checking"

    def test_fetch_accounts_type_filter_no_match(self, repo):
        """Test that type filter with no match returns empty list."""
        results = repo.fetch_accounts(account_type="crypto")

        assert results == []

    def test_fetch_accounts_empty_sheet(self, mock_sheets_service, repo):
        """Test that an empty sheet returns empty list."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert results == []

    def test_fetch_accounts_no_values_key(self, mock_sheets_service, repo):
        """Test that missing 'values' key returns empty list."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert results == []

    def test_short_rows_skipped(self, mock_sheets_service, repo):
        """Test that rows with fewer than 4 columns are skipped."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Too Short', 'checking'],
                ['2'],
                ['3', 'Valid Account', 'savings', '$10,000.00', '01/15/2025', 'Bank', 'Notes'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 1
        assert results[0].name == "Valid Account"

    def test_value_parsing(self, mock_sheets_service, repo):
        """Test that value parsing strips $ and , correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Dollar Sign', 'checking', '$5,000.50'],
                ['2', 'With Comma', 'savings', '$1,234,567.89'],
                ['3', 'Plain Number', 'investment', '42000.00'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 3
        assert results[0].value == 5000.50
        assert results[1].value == 1234567.89
        assert results[2].value == 42000.00

    def test_optional_fields_missing(self, mock_sheets_service, repo):
        """Test rows with fewer columns populate optional fields as None."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Minimal', 'checking', '$1,000.00'],
                ['2', 'With Date', 'savings', '$2,000.00', '06/15/2025'],
                ['3', 'With Institution', 'investment', '$3,000.00', '07/20/2025', 'Vanguard'],
                ['4', 'Full Row', 'checking', '$4,000.00', '08/01/2025', 'Chase', 'My notes'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 4

        assert results[0].last_updated is None
        assert results[0].institution is None
        assert results[0].notes is None

        assert results[1].last_updated == date(2025, 6, 15)
        assert results[1].institution is None
        assert results[1].notes is None

        assert results[2].last_updated == date(2025, 7, 20)
        assert results[2].institution == "Vanguard"
        assert results[2].notes is None

        assert results[3].last_updated == date(2025, 8, 1)
        assert results[3].institution == "Chase"
        assert results[3].notes == "My notes"

    def test_unparseable_dates_handled_gracefully(self, mock_sheets_service, repo):
        """Test that rows with unparseable dates still return with None last_updated."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Bad Date', 'checking', '$1,000.00', 'not-a-date', 'Chase', 'Notes'],
                ['2', 'Good Date', 'savings', '$2,000.00', '01/15/2025', 'Ally', 'Notes'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 2
        assert results[0].last_updated is None
        assert results[1].last_updated == date(2025, 1, 15)

    def test_sheet_not_found_raises(self, mock_sheets_service, repo):
        """Test that missing Assets sheet raises ValueError."""
        mock_get = MagicMock()
        mock_get.execute.return_value = {
            'sheets': [
                {'properties': {'title': '2025'}},
            ]
        }
        mock_sheets_service.spreadsheets().get.return_value = mock_get

        with pytest.raises(ValueError, match="Sheet 'Assets' does not exist"):
            repo.fetch_accounts()

    def test_api_called_with_correct_range(self, repo, mock_sheets_service):
        """Test that the API is called with the correct 'Assets'!A:G range."""
        repo.fetch_accounts()

        mock_sheets_service.spreadsheets().values().get.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            range="'Assets'!A:G",
        )

    def test_http_error_raises_exception(self, mock_sheets_service, repo):
        """Test that HttpError on fetching values is raised as Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().values().get.return_value.execute.side_effect = http_error

        with pytest.raises(Exception, match="Error fetching from sheet 'Assets'"):
            repo.fetch_accounts()

    def test_malformed_value_row_skipped(self, mock_sheets_service, repo):
        """Test that rows with unparseable values are skipped."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Bad Value', 'checking', 'not-a-number'],
                ['2', 'Good Value', 'savings', '$10,000.00'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 1
        assert results[0].name == "Good Value"

    def test_multiple_date_formats(self, mock_sheets_service, repo):
        """Test that MM/DD/YYYY, YYYY-MM-DD, and MM/DD/YY formats are parsed."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Format 1', 'checking', '$1,000.00', '01/15/2025'],
                ['2', 'Format 2', 'savings', '$2,000.00', '2025-06-20'],
                ['3', 'Format 3', 'investment', '$3,000.00', '09/10/25'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 3
        assert results[0].last_updated == date(2025, 1, 15)
        assert results[1].last_updated == date(2025, 6, 20)
        assert results[2].last_updated == date(2025, 9, 10)

    def test_empty_string_optional_fields_become_none(self, mock_sheets_service, repo):
        """Test that empty string values for institution and notes become None."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['1', 'Empty Fields', 'checking', '$1,000.00', '01/15/2025', '', ''],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_accounts()

        assert len(results) == 1
        assert results[0].institution is None
        assert results[0].notes is None


class TestFetchAssetsTool:
    """Test the fetch_assets MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._account_repository", None)
    @patch("server.get_account_repository")
    async def test_fetch_assets_tool_is_registered(self, mock_get_repo):
        """Test that fetch_assets tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "fetch_assets" in tools

    @pytest.mark.asyncio
    @patch("server._account_repository", None)
    @patch("server.get_account_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted response string with count and data."""
        mock_repo = MagicMock()
        mock_repo.fetch_accounts.return_value = [
            Account(
                id="1",
                name="Main Checking",
                type="checking",
                value=5000.00,
                last_updated=date(2025, 1, 15),
                institution="Chase",
                notes="Primary account",
            ),
        ]
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_assets"]

        result = await fetch_tool.run({})

        result_text = result.content[0].text
        assert "Found 1 assets" in result_text
        assert "Main Checking" in result_text
        assert "5000.0" in result_text

    @pytest.mark.asyncio
    @patch("server._account_repository", None)
    @patch("server.get_account_repository")
    async def test_returns_formatted_response_with_type_filter(self, mock_get_repo):
        """Test that the tool response includes filter info when type is specified."""
        mock_repo = MagicMock()
        mock_repo.fetch_accounts.return_value = [
            Account(
                id="1",
                name="Main Checking",
                type="checking",
                value=5000.00,
            ),
        ]
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_assets"]

        result = await fetch_tool.run({"account_type": "checking"})

        result_text = result.content[0].text
        assert "Found 1 assets" in result_text
        assert "of type 'checking'" in result_text

    @pytest.mark.asyncio
    @patch("server._account_repository", None)
    @patch("server.get_account_repository")
    async def test_fetch_assets_calls_repo_with_type(self, mock_get_repo):
        """Test that the tool passes account_type to the repository."""
        mock_repo = MagicMock()
        mock_repo.fetch_accounts.return_value = []
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_assets"]

        await fetch_tool.run({"account_type": "savings"})

        mock_repo.fetch_accounts.assert_called_once_with(account_type="savings")

    @pytest.mark.asyncio
    @patch("server._account_repository", None)
    @patch("server.get_account_repository")
    async def test_fetch_assets_repo_error_raises(self, mock_get_repo):
        """Test that repository ValueError is re-raised."""
        mock_repo = MagicMock()
        mock_repo.fetch_accounts.side_effect = ValueError("Sheet 'Assets' does not exist")
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_assets"]

        with pytest.raises(ValueError, match="Validation error"):
            await fetch_tool.run({})
