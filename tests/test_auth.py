"""Tests for Google Sheets authentication (google_sheets_auth module)."""

import base64
import json
import os
from unittest.mock import MagicMock, patch

import pytest


FAKE_SA_INFO = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "key123",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJBALRiMLAH\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}

FAKE_SA_B64 = base64.b64encode(json.dumps(FAKE_SA_INFO).encode()).decode()


@pytest.fixture(autouse=True)
def clean_modules():
    """Remove cached modules so each test gets fresh module-level globals."""
    import sys
    mods_to_remove = [k for k in sys.modules if k.startswith(("google_sheets_auth",))]
    for mod in mods_to_remove:
        del sys.modules[mod]
    yield
    mods_to_remove = [k for k in sys.modules if k.startswith(("google_sheets_auth",))]
    for mod in mods_to_remove:
        del sys.modules[mod]


class TestBase64Auth:
    """Test auth via GOOGLE_SERVICE_ACCOUNT_JSON_B64 env var."""

    @patch.dict(os.environ, {
        "GOOGLE_SERVICE_ACCOUNT_JSON_B64": FAKE_SA_B64,
        "GOOGLE_SERVICE_ACCOUNT_FILE": "",
    })
    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    @patch("googleapiclient.discovery.build")
    def test_uses_base64_when_set(self, mock_build, mock_from_info):
        mock_creds = MagicMock()
        mock_from_info.return_value = mock_creds
        mock_build.return_value = MagicMock()

        from google_sheets_auth import create_sheets_service
        service = create_sheets_service()

        mock_from_info.assert_called_once()
        call_args = mock_from_info.call_args
        assert call_args[0][0]["project_id"] == "test-project"
        assert service is not None

    @patch.dict(os.environ, {
        "GOOGLE_SERVICE_ACCOUNT_JSON_B64": FAKE_SA_B64,
        "GOOGLE_SERVICE_ACCOUNT_FILE": "",
    })
    @patch("google.oauth2.service_account.Credentials.from_service_account_info")
    @patch("google.oauth2.service_account.Credentials.from_service_account_file")
    @patch("googleapiclient.discovery.build")
    def test_base64_takes_priority_over_file(self, mock_build, mock_from_file, mock_from_info):
        mock_from_info.return_value = MagicMock()
        mock_build.return_value = MagicMock()

        from google_sheets_auth import create_sheets_service
        create_sheets_service()

        mock_from_info.assert_called_once()
        mock_from_file.assert_not_called()


class TestFileAuth:
    """Test auth via GOOGLE_SERVICE_ACCOUNT_FILE."""

    def test_uses_file_when_set(self, tmp_path):
        sa_file = tmp_path / "sa.json"
        sa_file.write_text(json.dumps(FAKE_SA_INFO))

        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64": "",
            "GOOGLE_SERVICE_ACCOUNT_FILE": str(sa_file),
        }), \
            patch("google.oauth2.service_account.Credentials.from_service_account_file") as mock_from_file, \
            patch("googleapiclient.discovery.build"):
            mock_from_file.return_value = MagicMock()

            from google_sheets_auth import create_sheets_service
            create_sheets_service()

            mock_from_file.assert_called_once()
            assert mock_from_file.call_args[0][0] == str(sa_file)

    def test_skips_file_when_path_missing(self):
        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64": "",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "/nonexistent/sa.json",
            "GOOGLE_CREDENTIALS_FILE": "/also/nonexistent/creds.json",
            "GOOGLE_TOKEN_FILE": "/also/nonexistent/token.json",
        }):
            from google_sheets_auth import create_sheets_service
            with pytest.raises(FileNotFoundError, match="No credentials found"):
                create_sheets_service()


class TestOAuthFallback:
    """Test OAuth fallback when no service account is configured."""

    def test_uses_cached_token(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_data = {
            "token": "ya29.fake",
            "refresh_token": "1//fake",
            "client_id": "fake.apps.googleusercontent.com",
            "client_secret": "fake-secret",
        }
        token_file.write_text(json.dumps(token_data))

        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64": "",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "",
            "GOOGLE_TOKEN_FILE": str(token_file),
            "GOOGLE_CREDENTIALS_FILE": "/nonexistent/creds.json",
        }), \
            patch("google.oauth2.credentials.Credentials.from_authorized_user_file") as mock_from_user, \
            patch("googleapiclient.discovery.build"):
            mock_creds = MagicMock()
            mock_creds.valid = True
            mock_from_user.return_value = mock_creds

            from google_sheets_auth import create_sheets_service
            service = create_sheets_service()

            mock_from_user.assert_called_once()
            assert service is not None

    def test_refreshes_expired_token(self, tmp_path):
        token_file = tmp_path / "token.json"
        token_file.write_text("{}")

        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64": "",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "",
            "GOOGLE_TOKEN_FILE": str(token_file),
            "GOOGLE_CREDENTIALS_FILE": "/nonexistent/creds.json",
        }), \
            patch("google.oauth2.credentials.Credentials.from_authorized_user_file") as mock_from_user, \
            patch("googleapiclient.discovery.build"):
            mock_creds = MagicMock()
            mock_creds.valid = False
            mock_creds.expired = True
            mock_creds.refresh_token = "1//fake"
            mock_creds.to_json.return_value = "{}"
            mock_from_user.return_value = mock_creds

            from google_sheets_auth import create_sheets_service
            service = create_sheets_service()

            mock_creds.refresh.assert_called_once()
            assert service is not None

    def test_raises_when_no_credentials_at_all(self):
        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64": "",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "",
            "GOOGLE_TOKEN_FILE": "/nonexistent/token.json",
            "GOOGLE_CREDENTIALS_FILE": "/nonexistent/creds.json",
        }):
            from google_sheets_auth import create_sheets_service
            with pytest.raises(FileNotFoundError, match="No credentials found"):
                create_sheets_service()
