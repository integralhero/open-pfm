"""Tests for fetch_flows functionality."""

from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from models import Flow
from repository import GoogleSheetsFlowRepository


@pytest.fixture
def mock_sheets_service():
    """Create a mock Google Sheets service."""
    mock_service = MagicMock()

    # Mock the spreadsheets().get() call for getting sheet names
    mock_get = MagicMock()
    mock_get.execute.return_value = {
        'sheets': [
            {'properties': {'title': '2025'}},
            {'properties': {'title': 'Recurring'}},
            {'properties': {'title': 'Assets'}},
        ]
    }
    mock_service.spreadsheets().get.return_value = mock_get

    # Mock the spreadsheets().values().get() call with default data
    mock_values_get = MagicMock()
    mock_values_get.execute.return_value = {
        'values': [
            ['Salary', '$5,000.00', 'Income', 'Monthly salary', 'TRUE', 'monthly'],
            ['Netflix', '-$15.99', 'Subscription', 'Streaming', 'TRUE', 'monthly'],
            ['Electric Bill', '-$120.00', 'Utilities', 'Power company', 'TRUE', 'monthly'],
            ['401k Contribution', '-$500.00', 'Traditional 401k', 'Pre-tax', 'TRUE', 'monthly'],
            ['Roth 401k', '-$200.00', 'Roth 401k', 'After-tax', 'FALSE', 'monthly'],
        ]
    }
    mock_service.spreadsheets().values().get.return_value = mock_values_get

    return mock_service


@pytest.fixture
def repo(mock_sheets_service):
    """Create a repository with an injected mock service."""
    return GoogleSheetsFlowRepository(
        service=mock_sheets_service,
        spreadsheet_id="test-spreadsheet-id",
    )


class TestFetchFlowsMethod:
    """Test the GoogleSheetsFlowRepository.fetch_flows method."""

    def test_fetch_flows_success(self, repo):
        """Test fetching all flows returns correct results."""
        results = repo.fetch_flows()

        assert len(results) == 5
        assert results[0].name == "Salary"
        assert results[0].amount == 5000.00
        assert results[0].category == "Income"
        assert results[0].description == "Monthly salary"
        assert results[0].active is True
        assert results[0].cadence == "monthly"

    def test_fetch_flows_negative_amount(self, repo):
        """Test that negative amounts (outflows) are parsed correctly."""
        results = repo.fetch_flows()

        assert results[1].name == "Netflix"
        assert results[1].amount == -15.99
        assert results[1].category == "Subscription"

    def test_category_filtering_case_insensitive(self, repo):
        """Test that category filtering is case-insensitive."""
        results = repo.fetch_flows(category="INCOME")

        assert len(results) == 1
        assert results[0].name == "Salary"
        assert results[0].category == "Income"

    def test_category_filter_no_match(self, repo):
        """Test that category filter with no match returns empty list."""
        results = repo.fetch_flows(category="nonexistent")

        assert results == []

    def test_active_only_true(self, repo):
        """Test filtering for active flows only."""
        results = repo.fetch_flows(active_only=True)

        assert len(results) == 4
        assert all(f.active is True for f in results)

    def test_active_only_false(self, repo):
        """Test filtering for inactive flows only."""
        results = repo.fetch_flows(active_only=False)

        assert len(results) == 1
        assert results[0].name == "Roth 401k"
        assert results[0].active is False

    def test_combined_category_and_active_filter(self, repo):
        """Test combining category and active_only filters."""
        results = repo.fetch_flows(category="Roth 401k", active_only=False)

        assert len(results) == 1
        assert results[0].name == "Roth 401k"

    def test_combined_filter_no_match(self, repo):
        """Test that combined filters with no match return empty list."""
        results = repo.fetch_flows(category="Income", active_only=False)

        assert results == []

    def test_empty_sheet(self, mock_sheets_service, repo):
        """Test that an empty sheet returns empty list."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results == []

    def test_no_values_key(self, mock_sheets_service, repo):
        """Test that missing 'values' key returns empty list."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results == []

    def test_short_rows_skipped(self, mock_sheets_service, repo):
        """Test that rows with fewer than 3 columns are skipped."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Too Short', '$100.00'],
                ['Only Name'],
                ['Valid Flow', '$500.00', 'Income', 'Description', 'TRUE', 'monthly'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 1
        assert results[0].name == "Valid Flow"

    def test_amount_parsing(self, mock_sheets_service, repo):
        """Test that amount parsing strips $ and , correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Dollar Sign', '$5,000.50', 'Income'],
                ['With Comma', '$1,234,567.89', 'Income'],
                ['Plain Number', '42000.00', 'Income'],
                ['Negative Dollar', '-$200.00', 'Utilities'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 4
        assert results[0].amount == 5000.50
        assert results[1].amount == 1234567.89
        assert results[2].amount == 42000.00
        assert results[3].amount == -200.00

    def test_status_parsing(self, mock_sheets_service, repo):
        """Test that TRUE/FALSE status strings are parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Active', '$100.00', 'Income', '', 'TRUE', 'monthly'],
                ['Inactive', '$200.00', 'Income', '', 'FALSE', 'monthly'],
                ['Lower True', '$300.00', 'Income', '', 'true', 'monthly'],
                ['Lower False', '$400.00', 'Income', '', 'false', 'monthly'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results[0].active is True
        assert results[1].active is False
        assert results[2].active is True
        assert results[3].active is False

    def test_cadence_parsing(self, mock_sheets_service, repo):
        """Test that cadence values are parsed correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Daily', '$100.00', 'Income', '', 'TRUE', 'daily'],
                ['Weekly', '$200.00', 'Income', '', 'TRUE', 'weekly'],
                ['Monthly', '$300.00', 'Income', '', 'TRUE', 'monthly'],
                ['Annually', '$400.00', 'Income', '', 'TRUE', 'annually'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results[0].cadence == "daily"
        assert results[1].cadence == "weekly"
        assert results[2].cadence == "monthly"
        assert results[3].cadence == "annually"

    def test_cadence_defaults_to_weekly_when_empty(self, mock_sheets_service, repo):
        """Test that empty cadence defaults to 'weekly'."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['No Cadence', '$100.00', 'Income', '', 'TRUE', ''],
                ['Whitespace Cadence', '$200.00', 'Income', '', 'TRUE', '   '],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results[0].cadence == "weekly"
        assert results[1].cadence == "weekly"

    def test_cadence_defaults_when_column_missing(self, mock_sheets_service, repo):
        """Test that missing cadence column defaults to 'weekly'."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['No Cadence Col', '$100.00', 'Income', '', 'TRUE'],
                ['Minimal', '$200.00', 'Income'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results[0].cadence == "weekly"
        assert results[1].cadence == "weekly"

    def test_optional_fields_missing(self, mock_sheets_service, repo):
        """Test rows with fewer columns populate optional fields with defaults."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Minimal', '$100.00', 'Income'],
                ['With Desc', '$200.00', 'Utilities', 'A description'],
                ['With Status', '$300.00', 'Subscription', 'Desc', 'FALSE'],
                ['Full Row', '$400.00', 'Income', 'Full desc', 'TRUE', 'annually'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 4

        assert results[0].description is None
        assert results[0].active is True
        assert results[0].cadence == "weekly"

        assert results[1].description == "A description"
        assert results[1].active is True
        assert results[1].cadence == "weekly"

        assert results[2].description == "Desc"
        assert results[2].active is False
        assert results[2].cadence == "weekly"

        assert results[3].description == "Full desc"
        assert results[3].active is True
        assert results[3].cadence == "annually"

    def test_empty_string_description_becomes_none(self, mock_sheets_service, repo):
        """Test that empty string description becomes None."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Empty Desc', '$100.00', 'Income', '', 'TRUE', 'monthly'],
                ['Whitespace Desc', '$200.00', 'Income', '   ', 'TRUE', 'monthly'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 2
        assert results[0].description is None
        assert results[1].description is None

    def test_status_defaults_to_true_when_empty(self, mock_sheets_service, repo):
        """Test that empty status string defaults to active (True)."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Empty Status', '$100.00', 'Income', 'Desc', '', 'monthly'],
                ['Whitespace Status', '$200.00', 'Income', 'Desc', '   ', 'monthly'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 2
        assert results[0].active is True
        assert results[1].active is True

    def test_sheet_not_found_raises(self, mock_sheets_service, repo):
        """Test that missing Recurring sheet raises ValueError."""
        mock_get = MagicMock()
        mock_get.execute.return_value = {
            'sheets': [
                {'properties': {'title': '2025'}},
                {'properties': {'title': 'Assets'}},
            ]
        }
        mock_sheets_service.spreadsheets().get.return_value = mock_get

        with pytest.raises(ValueError, match="Sheet 'Recurring' does not exist"):
            repo.fetch_flows()

    def test_api_called_with_correct_range(self, repo, mock_sheets_service):
        """Test that the API is called with the correct 'Recurring'!A:F range."""
        repo.fetch_flows()

        mock_sheets_service.spreadsheets().values().get.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            range="'Recurring'!A:F",
        )

    def test_http_error_raises_exception(self, mock_sheets_service, repo):
        """Test that HttpError on fetching values is raised as Exception."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )
        mock_sheets_service.spreadsheets().values().get.return_value.execute.side_effect = http_error

        with pytest.raises(Exception, match="Error fetching from sheet 'Recurring'"):
            repo.fetch_flows()

    def test_malformed_amount_row_skipped(self, mock_sheets_service, repo):
        """Test that rows with unparseable amounts are skipped."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Bad Amount', 'not-a-number', 'Income'],
                ['Good Amount', '$10,000.00', 'Income'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert len(results) == 1
        assert results[0].name == "Good Amount"

    def test_cadence_case_insensitive(self, mock_sheets_service, repo):
        """Test that cadence values are lowercased."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['Upper', '$100.00', 'Income', '', 'TRUE', 'MONTHLY'],
                ['Mixed', '$200.00', 'Income', '', 'TRUE', 'Weekly'],
                ['Lower', '$300.00', 'Income', '', 'TRUE', 'daily'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_flows()

        assert results[0].cadence == "monthly"
        assert results[1].cadence == "weekly"
        assert results[2].cadence == "daily"


class TestFetchFlowsTool:
    """Test the fetch_flows MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_fetch_flows_tool_is_registered(self, mock_get_repo):
        """Test that fetch_flows tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "fetch_flows" in tools

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted response string with count and data."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.return_value = [
            Flow(
                name="Salary",
                amount=5000.00,
                category="Income",
                description="Monthly salary",
                active=True,
                cadence="monthly",
            ),
            Flow(
                name="Netflix",
                amount=-15.99,
                category="Subscription",
                description="Streaming",
                active=True,
                cadence="monthly",
            ),
        ]
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        result = await fetch_tool.run({})

        result_text = result.content[0].text
        assert "Found 2 flows" in result_text
        assert "Salary" in result_text
        assert "Netflix" in result_text
        assert "5000.0" in result_text

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_returns_formatted_response_with_category_filter(self, mock_get_repo):
        """Test that the tool response includes filter info when category is specified."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.return_value = [
            Flow(
                name="Salary",
                amount=5000.00,
                category="Income",
            ),
        ]
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        result = await fetch_tool.run({"category": "Income"})

        result_text = result.content[0].text
        assert "Found 1 flows" in result_text
        assert "in category 'Income'" in result_text

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_returns_formatted_response_with_active_only(self, mock_get_repo):
        """Test that the tool response includes active filter info."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.return_value = []
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        result = await fetch_tool.run({"active_only": True})

        result_text = result.content[0].text
        assert "Found 0 flows" in result_text
        assert "(active only)" in result_text

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_returns_formatted_response_with_inactive_only(self, mock_get_repo):
        """Test that the tool response includes inactive filter info."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.return_value = []
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        result = await fetch_tool.run({"active_only": False})

        result_text = result.content[0].text
        assert "Found 0 flows" in result_text
        assert "(inactive only)" in result_text

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_fetch_flows_calls_repo_with_params(self, mock_get_repo):
        """Test that the tool passes parameters to the repository."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.return_value = []
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        await fetch_tool.run({"category": "Utilities", "active_only": True})

        mock_repo.fetch_flows.assert_called_once_with(
            category="Utilities",
            active_only=True,
        )

    @pytest.mark.asyncio
    @patch("server._flow_repository", None)
    @patch("server.get_flow_repository")
    async def test_fetch_flows_repo_error_raises(self, mock_get_repo):
        """Test that repository ValueError is re-raised."""
        mock_repo = MagicMock()
        mock_repo.fetch_flows.side_effect = ValueError("Sheet 'Recurring' does not exist")
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_flows"]

        with pytest.raises(ValueError, match="Validation error"):
            await fetch_tool.run({})
