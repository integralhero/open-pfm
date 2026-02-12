"""Transaction repository abstraction and Google Sheets implementation."""

import abc
from datetime import datetime, date
from typing import Optional

from googleapiclient.errors import HttpError

from models import Account, Flow, Transaction


class TransactionRepository(abc.ABC):
    """Abstract base class for transaction storage backends."""

    @abc.abstractmethod
    def fetch_transactions(
        self,
        start_date: date,
        end_date: date,
        category_filter: Optional[str] = None,
    ) -> list[Transaction]:
        ...

    @abc.abstractmethod
    def get_transaction(self, transaction_id: str) -> Transaction:
        ...

    @abc.abstractmethod
    def add_transaction(self, transaction: Transaction) -> Transaction:
        ...

    @abc.abstractmethod
    def delete_transaction(self, transaction_id: str) -> Transaction:
        ...

    @abc.abstractmethod
    def update_transaction(
        self,
        transaction_id: str,
        date: Optional[date] = None,
        name: Optional[str] = None,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Transaction:
        ...


class GoogleSheetsTransactionRepository(TransactionRepository):
    """Google Sheets implementation of the transaction repository."""

    def __init__(self, service, spreadsheet_id: str):
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    def _get_available_sheets(self) -> list[str]:
        """Get list of available sheet names from the spreadsheet."""
        try:
            result = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()

            return [sheet['properties']['title'] for sheet in result['sheets']]
        except HttpError as error:
            raise Exception(f"Error fetching sheet names: {error}")

    def _get_sheets_for_date_range(self, start_date: date, end_date: date) -> list[str]:
        """
        Determine which sheets to query based on date range.
        Assumes sheet names are years (e.g., '2023', '2024').
        """
        available_sheets = self._get_available_sheets()
        sheets_to_query = []

        for year in range(start_date.year, end_date.year + 1):
            year_str = str(year)
            if year_str in available_sheets:
                sheets_to_query.append(year_str)

        return sheets_to_query

    def fetch_transactions(
        self,
        start_date: date,
        end_date: date,
        category_filter: Optional[str] = None,
    ) -> list[Transaction]:
        """
        Fetch transactions from Google Spreadsheet across multiple sheets (years).

        Returns:
            List of transactions matching the criteria, sorted by date.
        """
        sheets_to_query = self._get_sheets_for_date_range(start_date, end_date)

        if not sheets_to_query:
            print(f"No sheets found for date range {start_date} to {end_date}")
            return []

        all_transactions = []

        for sheet_name in sheets_to_query:
            try:
                result = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{sheet_name}'!A:E"
                ).execute()

                values = result.get('values', [])
                if not values:
                    continue

                for row in values:
                    if len(row) < 3:
                        continue

                    try:
                        date_str = row[0]
                        transaction_date = None

                        try:
                            transaction_date = datetime.strptime(date_str, '%m/%d/%Y').date()
                        except ValueError:
                            try:
                                transaction_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            except ValueError:
                                for fmt in ['%m/%d/%y', '%d/%m/%Y', '%d/%m/%y']:
                                    try:
                                        transaction_date = datetime.strptime(date_str, fmt).date()
                                        break
                                    except ValueError:
                                        continue

                        if transaction_date is None:
                            print(f"Could not parse date: {date_str} in sheet {sheet_name}")
                            continue

                        if transaction_date < start_date or transaction_date > end_date:
                            continue

                        amount_str = row[2].replace('$', '').replace(',', '').strip()
                        amount = float(amount_str)

                        transaction = Transaction(
                            date=transaction_date,
                            name=row[1],
                            amount=amount,
                            description=row[3] if len(row) > 3 else None,
                            category=row[4] if len(row) > 4 else None
                        )

                        if category_filter and transaction.category:
                            if category_filter.lower() != transaction.category.lower():
                                continue

                        all_transactions.append(transaction)

                    except (ValueError, IndexError):
                        continue

            except HttpError as error:
                print(f"Error fetching from sheet {sheet_name}: {error}")
                continue

        all_transactions.sort(key=lambda x: x.date)

        return all_transactions

    def _parse_transaction_id(self, transaction_id: str) -> tuple[str, int]:
        """Parse a transaction ID into (year, row_number).

        Args:
            transaction_id: ID in '{year}-{row}' format (e.g., '2025-42').

        Returns:
            Tuple of (year_string, row_number).

        Raises:
            ValueError: If the ID format is invalid.
        """
        parts = transaction_id.split('-')
        if len(parts) != 2:
            raise ValueError(
                f"Invalid transaction ID format '{transaction_id}'. "
                "Expected '{year}-{row}' (e.g., '2025-42')."
            )

        year_str, row_str = parts

        try:
            int(year_str)
        except ValueError:
            raise ValueError(
                f"Invalid year '{year_str}' in transaction ID '{transaction_id}'."
            )

        try:
            row_number = int(row_str)
        except ValueError:
            raise ValueError(
                f"Invalid row number '{row_str}' in transaction ID '{transaction_id}'."
            )

        if row_number <= 0:
            raise ValueError(
                f"Row number must be positive, got {row_number} in transaction ID '{transaction_id}'."
            )

        return year_str, row_number

    def _parse_row(self, row: list[str]) -> dict:
        """Parse a single spreadsheet row into transaction field values.

        Args:
            row: List of cell values [date, name, amount, description?, category?].

        Returns:
            Dict with parsed fields: date, name, amount, description, category.

        Raises:
            ValueError: If the row cannot be parsed (too short, bad date, bad amount).
        """
        if len(row) < 3:
            raise ValueError(f"Row has fewer than 3 columns: {row}")

        date_str = row[0]
        transaction_date = None

        try:
            transaction_date = datetime.strptime(date_str, '%m/%d/%Y').date()
        except ValueError:
            try:
                transaction_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                for fmt in ['%m/%d/%y', '%d/%m/%Y', '%d/%m/%y']:
                    try:
                        transaction_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue

        if transaction_date is None:
            raise ValueError(f"Could not parse date: {date_str}")

        amount_str = row[2].replace('$', '').replace(',', '').strip()
        amount = float(amount_str)

        return {
            'date': transaction_date,
            'name': row[1],
            'amount': amount,
            'description': row[3] if len(row) > 3 else None,
            'category': row[4] if len(row) > 4 else None,
        }

    def get_transaction(self, transaction_id: str) -> Transaction:
        """
        Fetch a single transaction by its ID.

        Args:
            transaction_id: ID in '{year}-{row}' format (e.g., '2025-42').

        Returns:
            The Transaction at the given row with its id set.

        Raises:
            ValueError: If the ID is invalid, the sheet doesn't exist, or the row is empty/unparseable.
        """
        year_str, row_number = self._parse_transaction_id(transaction_id)

        available_sheets = self._get_available_sheets()
        if year_str not in available_sheets:
            raise ValueError(
                f"Sheet '{year_str}' does not exist in the spreadsheet. "
                f"Available sheets: {', '.join(available_sheets)}"
            )

        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{year_str}'!A{row_number}:E{row_number}"
            ).execute()
        except HttpError as error:
            raise Exception(f"Error fetching transaction {transaction_id}: {error}")

        values = result.get('values', [])
        if not values or not values[0]:
            raise ValueError(
                f"No transaction found at row {row_number} in sheet '{year_str}'."
            )

        row = values[0]

        try:
            fields = self._parse_row(row)
        except ValueError as e:
            raise ValueError(
                f"Could not parse transaction at {transaction_id}: {e}"
            )

        return Transaction(id=transaction_id, **fields)

    def add_transaction(self, transaction: Transaction) -> Transaction:
        """
        Add a new transaction to the appropriate year sheet.

        Args:
            transaction: The Transaction to persist.

        Returns:
            The same Transaction object on success.
        """
        sheet_name = str(transaction.date.year)

        available_sheets = self._get_available_sheets()
        if sheet_name not in available_sheets:
            raise ValueError(
                f"Sheet '{sheet_name}' does not exist in the spreadsheet. "
                f"Available sheets: {', '.join(available_sheets)}"
            )

        formatted_date = transaction.date.strftime('%m/%d/%Y')
        formatted_amount = f"${transaction.amount:.2f}"

        row_data = [
            formatted_date,
            transaction.name,
            formatted_amount,
            transaction.description or "",
            transaction.category or "",
        ]

        try:
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet_name}'!A:E",
                valueInputOption='USER_ENTERED',
                insertDataOption='INSERT_ROWS',
                body={'values': [row_data]}
            ).execute()

            return transaction

        except HttpError as error:
            raise Exception(f"Error adding transaction to sheet {sheet_name}: {error}")

    def _get_sheet_id(self, sheet_name: str) -> int:
        """Get the numeric sheet ID for a given sheet name.

        Args:
            sheet_name: The sheet title (e.g., '2025').

        Returns:
            The numeric sheetId used by batchUpdate requests.

        Raises:
            ValueError: If no sheet with that name exists.
        """
        try:
            result = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()

            for sheet in result['sheets']:
                if sheet['properties']['title'] == sheet_name:
                    return sheet['properties']['sheetId']

            raise ValueError(f"Sheet '{sheet_name}' not found in spreadsheet.")
        except HttpError as error:
            raise Exception(f"Error fetching sheet ID for '{sheet_name}': {error}")

    def delete_transaction(self, transaction_id: str) -> Transaction:
        """
        Delete a transaction by its ID.

        Args:
            transaction_id: ID in '{year}-{row}' format (e.g., '2025-42').

        Returns:
            The deleted Transaction.

        Raises:
            ValueError: If the ID is invalid, the sheet doesn't exist, or the row is empty.
        """
        year_str, row_number = self._parse_transaction_id(transaction_id)

        transaction = self.get_transaction(transaction_id)

        sheet_id = self._get_sheet_id(year_str)

        try:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    'requests': [{
                        'deleteDimension': {
                            'range': {
                                'sheetId': sheet_id,
                                'dimension': 'ROWS',
                                'startIndex': row_number - 1,
                                'endIndex': row_number,
                            }
                        }
                    }]
                }
            ).execute()

            return transaction

        except HttpError as error:
            raise Exception(f"Error deleting transaction {transaction_id}: {error}")

    def update_transaction(
        self,
        transaction_id: str,
        date: Optional[date] = None,
        name: Optional[str] = None,
        amount: Optional[float] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Transaction:
        """
        Update a transaction by its ID with the provided fields.

        Only the fields that are not None will be updated; the rest keep their
        existing values.

        Args:
            transaction_id: ID in '{year}-{row}' format (e.g., '2025-42').
            date: New date for the transaction.
            name: New name/title for the transaction.
            amount: New amount for the transaction.
            description: New description/note for the transaction.
            category: New category for the transaction.

        Returns:
            The updated Transaction.

        Raises:
            ValueError: If the ID is invalid, the sheet doesn't exist,
                the row is empty, or the new date's year doesn't match the sheet.
        """
        year_str, row_number = self._parse_transaction_id(transaction_id)

        existing = self.get_transaction(transaction_id)

        # Merge updates onto the existing transaction
        updated_date = date if date is not None else existing.date
        updated_name = name if name is not None else existing.name
        updated_amount = amount if amount is not None else existing.amount
        updated_description = description if description is not None else existing.description
        updated_category = category if category is not None else existing.category

        # Prevent cross-year date moves (the row lives in a specific year sheet)
        if str(updated_date.year) != year_str:
            raise ValueError(
                f"Cannot change date to a different year ({updated_date.year}) "
                f"than the transaction's sheet ({year_str}). "
                "Delete and re-add the transaction instead."
            )

        formatted_date = updated_date.strftime('%m/%d/%Y')
        formatted_amount = f"${updated_amount:.2f}"

        row_data = [
            formatted_date,
            updated_name,
            formatted_amount,
            updated_description or "",
            updated_category or "",
        ]

        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{year_str}'!A{row_number}:E{row_number}",
                valueInputOption='USER_ENTERED',
                body={'values': [row_data]},
            ).execute()
        except HttpError as error:
            raise Exception(f"Error updating transaction {transaction_id}: {error}")

        return Transaction(
            id=transaction_id,
            date=updated_date,
            name=updated_name,
            amount=updated_amount,
            description=updated_description,
            category=updated_category,
        )


class AccountRepository(abc.ABC):
    """Abstract base class for account/asset storage backends."""

    @abc.abstractmethod
    def fetch_accounts(
        self,
        account_type: Optional[str] = None,
    ) -> list[Account]:
        ...


class GoogleSheetsAccountRepository(AccountRepository):
    """Google Sheets implementation of the account repository."""

    SHEET_NAME = "Assets"

    def __init__(self, service, spreadsheet_id: str):
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    def _get_available_sheets(self) -> list[str]:
        """Get list of available sheet names from the spreadsheet."""
        try:
            result = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            return [sheet['properties']['title'] for sheet in result['sheets']]
        except HttpError as error:
            raise Exception(f"Error fetching sheet names: {error}")

    def _parse_value(self, value_str: str) -> float:
        """Parse a monetary value string into a float."""
        return float(value_str.replace('$', '').replace(',', '').strip())

    def _parse_date(self, date_str: str) -> date:
        """Parse a date string, trying multiple formats.

        Raises:
            ValueError: If no format matches.
        """
        for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%m/%d/%y', '%d/%m/%Y', '%d/%m/%y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Could not parse date: {date_str}")

    def fetch_accounts(
        self,
        account_type: Optional[str] = None,
    ) -> list[Account]:
        """
        Fetch accounts/assets from the Assets sheet.

        Args:
            account_type: Optional type filter (case-insensitive).

        Returns:
            List of Account objects matching the criteria.

        Raises:
            ValueError: If the Assets sheet does not exist.
        """
        available_sheets = self._get_available_sheets()
        if self.SHEET_NAME not in available_sheets:
            raise ValueError(
                f"Sheet '{self.SHEET_NAME}' does not exist in the spreadsheet. "
                f"Available sheets: {', '.join(available_sheets)}"
            )

        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{self.SHEET_NAME}'!A:G",
            ).execute()
        except HttpError as error:
            raise Exception(f"Error fetching from sheet '{self.SHEET_NAME}': {error}")

        values = result.get('values', [])
        if not values:
            return []

        accounts = []
        for row in values:
            # Need at least id, name, type, value (4 columns)
            if len(row) < 4:
                continue

            try:
                value = self._parse_value(row[3])

                last_updated = None
                if len(row) > 4 and row[4].strip():
                    try:
                        last_updated = self._parse_date(row[4])
                    except ValueError:
                        pass

                account = Account(
                    id=row[0],
                    name=row[1],
                    type=row[2],
                    value=value,
                    last_updated=last_updated,
                    institution=row[5] if len(row) > 5 and row[5].strip() else None,
                    notes=row[6] if len(row) > 6 and row[6].strip() else None,
                )

                if account_type:
                    if account_type.lower() != account.type.lower():
                        continue

                accounts.append(account)

            except (ValueError, IndexError):
                continue

        return accounts


class FlowRepository(abc.ABC):
    """Abstract base class for recurring flow storage backends."""

    @abc.abstractmethod
    def fetch_flows(
        self,
        category: Optional[str] = None,
        active_only: Optional[bool] = None,
    ) -> list[Flow]:
        ...


class GoogleSheetsFlowRepository(FlowRepository):
    """Google Sheets implementation of the flow repository."""

    SHEET_NAME = "Recurring"

    def __init__(self, service, spreadsheet_id: str):
        self.service = service
        self.spreadsheet_id = spreadsheet_id

    def _get_available_sheets(self) -> list[str]:
        """Get list of available sheet names from the spreadsheet."""
        try:
            result = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            ).execute()
            return [sheet['properties']['title'] for sheet in result['sheets']]
        except HttpError as error:
            raise Exception(f"Error fetching sheet names: {error}")

    def _parse_amount(self, amount_str: str) -> float:
        """Parse a monetary value string into a float."""
        return float(amount_str.replace('$', '').replace(',', '').strip())

    def _parse_status(self, status_str: str) -> bool:
        """Parse a status string into a boolean.

        Accepts 'TRUE'/'FALSE' (case-insensitive).
        """
        return status_str.strip().upper() == "TRUE"

    def _parse_cadence(self, cadence_str: str) -> str:
        """Parse a cadence string, defaulting to 'weekly' if empty."""
        stripped = cadence_str.strip().lower()
        return stripped if stripped else "weekly"

    def fetch_flows(
        self,
        category: Optional[str] = None,
        active_only: Optional[bool] = None,
    ) -> list[Flow]:
        """
        Fetch recurring flows from the Recurring sheet.

        Args:
            category: Optional category filter (case-insensitive).
            active_only: If True, only return active flows. If False, only
                inactive. If None, return all.

        Returns:
            List of Flow objects matching the criteria.

        Raises:
            ValueError: If the Recurring sheet does not exist.
        """
        available_sheets = self._get_available_sheets()
        if self.SHEET_NAME not in available_sheets:
            raise ValueError(
                f"Sheet '{self.SHEET_NAME}' does not exist in the spreadsheet. "
                f"Available sheets: {', '.join(available_sheets)}"
            )

        try:
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{self.SHEET_NAME}'!A:F",
            ).execute()
        except HttpError as error:
            raise Exception(f"Error fetching from sheet '{self.SHEET_NAME}': {error}")

        values = result.get('values', [])
        if not values:
            return []

        flows = []
        for row in values:
            # Need at least name, amount, category (3 columns)
            if len(row) < 3:
                continue

            try:
                amount = self._parse_amount(row[1])

                description = row[3] if len(row) > 3 and row[3].strip() else None
                active = self._parse_status(row[4]) if len(row) > 4 and row[4].strip() else True
                cadence = self._parse_cadence(row[5]) if len(row) > 5 else "weekly"

                flow = Flow(
                    name=row[0],
                    amount=amount,
                    category=row[2],
                    description=description,
                    active=active,
                    cadence=cadence,
                )

                if category:
                    if category.lower() != flow.category.lower():
                        continue

                if active_only is not None:
                    if flow.active != active_only:
                        continue

                flows.append(flow)

            except (ValueError, IndexError):
                continue

        return flows
