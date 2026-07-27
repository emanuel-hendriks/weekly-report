"""Tests for Assets API resolution in fetch_jira.py."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from weekly_recap.fetchers.fetch_jira import (
    _fetch_asset_label,
    _resolve_asset_object,
    resolve_assets_labels,
)


class TestFetchAssetLabel:
    """Tests for _fetch_asset_label — single API call with pre-built auth."""

    def test_returns_label_on_success(self):
        import ssl
        cache = {}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"label": "Banca Mediolanum SPA"}).encode()

        with patch("urllib.request.urlopen", return_value=mock_response):
            ssl_ctx = ssl.create_default_context()
            result = _fetch_asset_label("131", "fake-auth", ssl_ctx, cache)

        assert result == "Banca Mediolanum SPA"
        assert cache["131"] == "Banca Mediolanum SPA"

    def test_returns_none_on_http_error(self):
        import ssl
        import urllib.error
        cache = {}

        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs={}, fp=None
        )):
            ssl_ctx = ssl.create_default_context()
            result = _fetch_asset_label("999", "fake-auth", ssl_ctx, cache)

        assert result is None
        assert "999" not in cache

    def test_returns_none_on_empty_label(self):
        import ssl
        cache = {}
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"label": ""}).encode()

        with patch("urllib.request.urlopen", return_value=mock_response):
            ssl_ctx = ssl.create_default_context()
            result = _fetch_asset_label("131", "fake-auth", ssl_ctx, cache)

        assert result is None
        assert "131" not in cache

    def test_uses_cache_hit(self):
        """_fetch_asset_label doesn't check cache — that's the caller's job.
        But _resolve_asset_object does."""
        cache = {"131": "Cached Label"}
        result = _resolve_asset_object("131", cache)
        assert result == "Cached Label"


class TestResolveAssetObject:
    """Tests for _resolve_asset_object — convenience wrapper."""

    def test_returns_cached_value_without_api_call(self):
        cache = {"42": "Already Resolved"}
        result = _resolve_asset_object("42", cache)
        assert result == "Already Resolved"

    def test_returns_none_when_auth_unavailable(self, tmp_path):
        with patch("weekly_recap.fetchers.fetch_jira.pathlib.Path.home", return_value=tmp_path):
            cache = {}
            result = _resolve_asset_object("999", cache)
            assert result is None


class TestResolveAssetsLabels:
    """Tests for resolve_assets_labels — batch resolution with auth reuse."""

    def test_no_object_ids_maps_environment_only(self):
        issues = [
            {
                "key": "CPS-100",
                "customer_object_ids": [],
                "service_object_ids": [],
                "assets_object_ids": [],
                "environment_cloud": "Staging",
                "cloud_environments": [],
                "tenant_text": None,
            }
        ]
        result = resolve_assets_labels(issues)
        assert result[0]["customer_label"] is None
        assert result[0]["environment_resolved"] == "STAG"

    def test_uses_tenant_text_fallback(self):
        issues = [
            {
                "key": "AWS-200",
                "customer_object_ids": [],
                "service_object_ids": [],
                "assets_object_ids": [],
                "environment_cloud": None,
                "cloud_environments": ["Development"],
                "tenant_text": "BMEDPFT",
            }
        ]
        result = resolve_assets_labels(issues)
        assert result[0]["customer_label"] == "BMEDPFT"
        assert result[0]["environment_resolved"] == "DEV"

    @patch("weekly_recap.fetchers.fetch_jira.prepare_jira_auth")
    @patch("weekly_recap.fetchers.fetch_jira._fetch_asset_label")
    @patch("weekly_recap.fetchers.fetch_jira._load_assets_cache", return_value={})
    @patch("weekly_recap.fetchers.fetch_jira._save_assets_cache")
    def test_resolves_customer_object_ids(self, mock_save, mock_load, mock_fetch, mock_auth):
        mock_auth.return_value = ("fake-auth", "test@example.com")
        mock_fetch.side_effect = lambda oid, auth, ssl, cache: (
            cache.update({"131": "Poste Italiane SPA"}) or "Poste Italiane SPA"
            if oid == "131" else None
        )

        issues = [
            {
                "key": "CPS-300",
                "customer_object_ids": ["131"],
                "service_object_ids": [],
                "assets_object_ids": [],
                "environment_cloud": "Prod",
                "cloud_environments": [],
                "tenant_text": None,
            }
        ]
        result = resolve_assets_labels(issues)
        assert result[0]["customer_label"] == "Poste Italiane SPA"
        assert result[0]["environment_resolved"] == "PROD"
        mock_auth.assert_called_once()

    @patch("weekly_recap.fetchers.fetch_jira.prepare_jira_auth", return_value=None)
    @patch("weekly_recap.fetchers.fetch_jira._load_assets_cache", return_value={"131": "Cached Co"})
    def test_uses_cache_when_auth_fails(self, mock_load, mock_auth):
        issues = [
            {
                "key": "CPS-400",
                "customer_object_ids": ["131"],
                "service_object_ids": [],
                "assets_object_ids": [],
                "environment_cloud": None,
                "cloud_environments": [],
                "tenant_text": None,
            }
        ]
        result = resolve_assets_labels(issues)
        # Should still use cached value even though auth failed
        assert result[0]["customer_label"] == "Cached Co"
