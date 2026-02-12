"""Tests for fetch_transactions functionality."""

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

    # Mock the spreadsheets().values().get() call with default data
    mock_values_get = MagicMock()
    mock_values_get.execute.return_value = {
        'values': [
            ['01/15/2025', 'Coffee Shop', '$5.50', 'Morning coffee', 'Food'],
            ['02/20/2025', 'Gas Station', '$45.00', 'Fill up', 'Transportation'],
            ['03/10/2025', 'Amazon', '$29.99', 'Book purchase', 'Shopping'],
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


class TestFetchTransactionsMethod:
    """Test the GoogleSheetsTransactionRepository.fetch_transactions method."""

    def test_fetch_transactions_success(self, repo):
        """Test fetching transactions within a date range returns correct results."""
        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 3
        assert results[0].date == date(2025, 1, 15)
        assert results[0].name == "Coffee Shop"
        assert results[0].amount == 999.99  # intentionally wrong to test CI
        assert results[0].description == "Morning coffee"
        assert results[0].category == "Food"

    def test_category_filtering_case_insensitive(self, repo):
        """Test that category filtering is case-insensitive."""
        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            category_filter="food",
        )

        assert len(results) == 1
        assert results[0].category == "Food"

    def test_category_filter_no_match(self, repo):
        """Test that category filter with no match returns empty list."""
        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            category_filter="Healthcare",
        )

        assert results == []

    def test_multi_year_date_range(self, mock_sheets_service, repo):
        """Test that multi-year date ranges query both year sheets."""
        # Set up different data for each year sheet
        def values_get_side_effect(**kwargs):
            mock_result = MagicMock()
            if "'2025'" in kwargs.get('range', ''):
                mock_result.execute.return_value = {
                    'values': [
                        ['12/01/2025', 'Dec Purchase', '$10.00', 'Note', 'Misc'],
                    ]
                }
            elif "'2026'" in kwargs.get('range', ''):
                mock_result.execute.return_value = {
                    'values': [
                        ['01/15/2026', 'Jan Purchase', '$20.00', 'Note', 'Misc'],
                    ]
                }
            return mock_result

        mock_sheets_service.spreadsheets().values().get.side_effect = values_get_side_effect

        results = repo.fetch_transactions(
            start_date=date(2025, 11, 1),
            end_date=date(2026, 2, 28),
        )

        assert len(results) == 2
        assert results[0].date == date(2025, 12, 1)
        assert results[1].date == date(2026, 1, 15)

    def test_no_matching_sheets(self, mock_sheets_service, repo):
        """Test that querying a year with no sheet returns empty list."""
        results = repo.fetch_transactions(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
        )

        assert results == []

    def test_empty_sheet(self, mock_sheets_service, repo):
        """Test that an empty sheet returns empty list."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {'values': []}
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert results == []

    def test_short_rows_skipped(self, mock_sheets_service, repo):
        """Test that rows with fewer than 3 columns are skipped."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['01/15/2025', 'Only Two Columns'],
                ['01/15/2025'],
                ['02/20/2025', 'Valid Row', '$10.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 1
        assert results[0].name == "Valid Row"

    def test_unparseable_dates_skipped(self, mock_sheets_service, repo):
        """Test that rows with unparseable dates are skipped without crashing."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['not-a-date', 'Bad Date', '$10.00', 'Note', 'Food'],
                ['gibberish', 'Also Bad', '$5.00', 'Note', 'Misc'],
                ['02/20/2025', 'Good Date', '$15.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 1
        assert results[0].name == "Good Date"

    def test_transactions_outside_range_filtered(self, mock_sheets_service, repo):
        """Test that only transactions within the date range are returned."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['01/15/2025', 'Too Early', '$5.00', 'Note', 'Food'],
                ['06/15/2025', 'In Range', '$10.00', 'Note', 'Food'],
                ['12/31/2025', 'Too Late', '$15.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 3, 1),
            end_date=date(2025, 9, 30),
        )

        assert len(results) == 1
        assert results[0].name == "In Range"

    def test_results_sorted_by_date(self, mock_sheets_service, repo):
        """Test that results are sorted by date ascending."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['03/15/2025', 'Third', '$30.00', 'Note', 'Food'],
                ['01/10/2025', 'First', '$10.00', 'Note', 'Food'],
                ['02/20/2025', 'Second', '$20.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 3
        assert results[0].name == "First"
        assert results[1].name == "Second"
        assert results[2].name == "Third"

    def test_optional_fields_missing(self, mock_sheets_service, repo):
        """Test rows with 3-4 columns populate description/category as None."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['01/15/2025', 'No Desc No Cat', '$5.00'],
                ['02/20/2025', 'Has Desc No Cat', '$10.00', 'A description'],
                ['03/10/2025', 'Has Both', '$15.00', 'Desc', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 3

        assert results[0].description is None
        assert results[0].category is None

        assert results[1].description == "A description"
        assert results[1].category is None

        assert results[2].description == "Desc"
        assert results[2].category == "Food"

    def test_amount_parsing(self, mock_sheets_service, repo):
        """Test that amount parsing strips $ and , correctly."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['01/15/2025', 'Dollar Sign', '$5.50', 'Note', 'Food'],
                ['02/20/2025', 'With Comma', '$1,234.56', 'Note', 'Food'],
                ['03/10/2025', 'Plain Number', '42.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 3
        assert results[0].amount == 5.50
        assert results[1].amount == 1234.56
        assert results[2].amount == 42.00

    def test_multiple_date_formats(self, mock_sheets_service, repo):
        """Test that MM/DD/YYYY, YYYY-MM-DD, and MM/DD/YY formats are parsed."""
        mock_values_get = MagicMock()
        mock_values_get.execute.return_value = {
            'values': [
                ['01/15/2025', 'MM/DD/YYYY', '$5.00', 'Note', 'Food'],
                ['2025-06-20', 'YYYY-MM-DD', '$10.00', 'Note', 'Food'],
                ['09/10/25', 'MM/DD/YY', '$15.00', 'Note', 'Food'],
            ]
        }
        mock_sheets_service.spreadsheets().values().get.return_value = mock_values_get

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(results) == 3
        assert results[0].date == date(2025, 1, 15)
        assert results[1].date == date(2025, 6, 20)
        assert results[2].date == date(2025, 9, 10)

    def test_http_error_on_sheet_continues(self, mock_sheets_service, repo):
        """Test that HttpError on one sheet gracefully continues to next."""
        http_error = HttpError(
            resp=MagicMock(status=500),
            content=b"Internal Server Error",
        )

        def values_get_side_effect(**kwargs):
            mock_result = MagicMock()
            if "'2025'" in kwargs.get('range', ''):
                raise http_error
            elif "'2026'" in kwargs.get('range', ''):
                mock_result.execute.return_value = {
                    'values': [
                        ['01/15/2026', 'From 2026', '$10.00', 'Note', 'Misc'],
                    ]
                }
            return mock_result

        mock_sheets_service.spreadsheets().values().get.side_effect = values_get_side_effect

        results = repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2026, 12, 31),
        )

        assert len(results) == 1
        assert results[0].name == "From 2026"

    def test_api_called_with_correct_range(self, repo, mock_sheets_service):
        """Test that the API is called with the correct '{year}'!A:E range."""
        repo.fetch_transactions(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        mock_sheets_service.spreadsheets().values().get.assert_called_with(
            spreadsheetId="test-spreadsheet-id",
            range="'2025'!A:E",
        )


class TestFetchTransactionsTool:
    """Test the fetch_transactions MCP tool registration and behavior."""

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_fetch_transactions_tool_is_registered(self, mock_get_repo):
        """Test that fetch_transactions tool is registered with FastMCP."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        assert "fetch_transactions" in tools

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_start_date_after_end_date_raises(self, mock_get_repo):
        """Test that start_date after end_date raises ValueError."""
        mock_get_repo.return_value = MagicMock()

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_transactions"]

        with pytest.raises(ValueError, match="Start date must be before or equal to end date"):
            await fetch_tool.run(
                {"start_date": "2025-12-31", "end_date": "2025-01-01"},
            )

    @pytest.mark.asyncio
    @patch("server._repository", None)
    @patch("server.get_repository")
    async def test_returns_formatted_response(self, mock_get_repo):
        """Test that the tool returns a formatted response string with count and data."""
        mock_repo = MagicMock()
        mock_repo.fetch_transactions.return_value = [
            Transaction(
                date=date(2025, 1, 15),
                name="Coffee",
                amount=5.50,
                description="Morning coffee",
                category="Food",
            ),
        ]
        mock_get_repo.return_value = mock_repo

        from server import app

        tools = await app.get_tools()
        fetch_tool = tools["fetch_transactions"]

        result = await fetch_tool.run(
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        )

        result_text = result.content[0].text
        assert "Found 1 transactions" in result_text
        assert "2025-01-01" in result_text
        assert "2025-12-31" in result_text
        assert "Coffee" in result_text
