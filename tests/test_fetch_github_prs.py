"""Unit tests for weekly_recap/fetchers/fetch_github_prs.py (httpx version)."""

import json
from unittest.mock import patch, MagicMock

import pytest

from weekly_recap.fetchers.fetch_github_prs import (
    validate_iso_date,
    validate_inputs,
    normalize_pr,
    deduplicate_prs,
    build_queries,
    main,
)


class TestValidateIsoDate:
    def test_valid_date(self):
        assert validate_iso_date("2026-01-15") is True

    def test_valid_date_leap_year(self):
        assert validate_iso_date("2024-02-29") is True

    def test_invalid_format(self):
        assert validate_iso_date("01-15-2026") is False

    def test_invalid_date(self):
        assert validate_iso_date("2026-13-01") is False

    def test_empty_string(self):
        assert validate_iso_date("") is False

    def test_none(self):
        assert validate_iso_date(None) is False


class TestValidateInputs:
    def test_valid_inputs(self):
        assert validate_inputs("user", ["org1"], "2026-01-01", "2026-01-07") is None

    def test_empty_handle(self):
        result = validate_inputs("", ["org1"], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "github_handle" in result

    def test_whitespace_handle(self):
        result = validate_inputs("   ", ["org1"], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "github_handle" in result

    def test_empty_orgs(self):
        result = validate_inputs("user", [], "2026-01-01", "2026-01-07")
        assert result is not None
        assert "org" in result.lower()

    def test_invalid_start_date(self):
        result = validate_inputs("user", ["org1"], "not-a-date", "2026-01-07")
        assert result is not None
        assert "start_date" in result

    def test_invalid_end_date(self):
        result = validate_inputs("user", ["org1"], "2026-01-01", "2026-13-07")
        assert result is not None
        assert "end_date" in result


class TestNormalizePr:
    def test_merged_pr(self):
        raw = {
            "number": 7,
            "title": "feat: add feature",
            "state": "closed",
            "html_url": "https://github.com/org/repo/pull/7",
            "created_at": "2026-05-13T10:00:00Z",
            "closed_at": "2026-05-14T12:00:00Z",
            "repository_url": "https://api.github.com/repos/org/repo",
        }
        result = normalize_pr(raw, "org", "merged")
        assert result["number"] == 7
        assert result["title"] == "feat: add feature"
        assert result["state"] == "closed"
        assert result["category"] == "merged"
        assert result["repo"] == "repo"
        assert result["org"] == "org"
        assert result["html_url"] == "https://github.com/org/repo/pull/7"
        assert result["created_at"] == "2026-05-13"
        assert result["merged_at"] == "2026-05-14"

    def test_closed_unmerged_pr(self):
        raw = {
            "number": 5,
            "title": "fix: broken thing",
            "state": "closed",
            "html_url": "https://github.com/org/repo/pull/5",
            "created_at": "2026-05-12T08:00:00Z",
            "closed_at": "2026-05-13T09:00:00Z",
            "repository_url": "https://api.github.com/repos/org/repo",
        }
        result = normalize_pr(raw, "org", "closed")
        assert result["state"] == "closed"
        assert result["category"] == "closed"
        assert result["merged_at"] is None

    def test_open_pr(self):
        raw = {
            "number": 10,
            "title": "wip: new feature",
            "state": "open",
            "html_url": "https://github.com/org/repo/pull/10",
            "created_at": "2026-05-15T08:00:00Z",
            "closed_at": None,
            "repository_url": "https://api.github.com/repos/my-org/repo",
        }
        result = normalize_pr(raw, "my-org", "created")
        assert result["state"] == "open"
        assert result["category"] == "open"
        assert result["org"] == "my-org"
        assert result["merged_at"] is None

    def test_created_query_closed_pr_defaults_to_closed_category(self):
        raw = {
            "number": 3,
            "title": "some PR",
            "state": "closed",
            "html_url": "https://github.com/org/repo/pull/3",
            "created_at": "2026-05-10T08:00:00Z",
            "closed_at": "2026-05-11T09:00:00Z",
            "repository_url": "https://api.github.com/repos/org/repo",
        }
        result = normalize_pr(raw, "org", "created")
        assert result["state"] == "closed"
        assert result["category"] == "closed"
        assert result["merged_at"] is None


class TestDeduplicatePrs:
    def test_no_duplicates(self):
        prs = [
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "open"},
            {"html_url": "https://github.com/org/repo/pull/2", "number": 2, "category": "open"},
        ]
        result = deduplicate_prs(prs)
        assert len(result) == 2

    def test_with_duplicates(self):
        prs = [
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "open"},
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "open"},
            {"html_url": "https://github.com/org/repo/pull/2", "number": 2, "category": "open"},
        ]
        result = deduplicate_prs(prs)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate_prs([]) == []

    def test_prefers_merged_over_closed(self):
        prs = [
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "closed"},
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "merged"},
        ]
        result = deduplicate_prs(prs)
        assert len(result) == 1
        assert result[0]["category"] == "merged"

    def test_prefers_closed_over_open(self):
        prs = [
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "open"},
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "closed"},
        ]
        result = deduplicate_prs(prs)
        assert len(result) == 1
        assert result[0]["category"] == "closed"

    def test_keeps_higher_priority_when_first(self):
        prs = [
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "merged"},
            {"html_url": "https://github.com/org/repo/pull/1", "number": 1, "category": "closed"},
        ]
        result = deduplicate_prs(prs)
        assert len(result) == 1
        assert result[0]["category"] == "merged"


class TestBuildQueries:
    def test_produces_3_queries(self):
        queries = build_queries("user", "org1", "2026-01-01", "2026-01-07")
        assert len(queries) == 3

    def test_created_query(self):
        queries = build_queries("user", "org1", "2026-01-01", "2026-01-07")
        query_str, label = queries[0]
        assert "author:user" in query_str
        assert "org:org1" in query_str
        assert "created:2026-01-01..2026-01-07" in query_str
        assert label == "created"

    def test_merged_query(self):
        queries = build_queries("user", "org1", "2026-01-01", "2026-01-07")
        query_str, label = queries[1]
        assert "merged:2026-01-01..2026-01-07" in query_str
        assert label == "merged"

    def test_closed_unmerged_query(self):
        queries = build_queries("user", "org1", "2026-01-01", "2026-01-07")
        query_str, label = queries[2]
        assert "closed:2026-01-01..2026-01-07" in query_str
        assert "-is:merged" in query_str
        assert label == "closed"


class TestMainExitCodes:
    @patch("weekly_recap.fetchers.fetch_github_prs.get_github_token")
    def test_exit_1_no_token(self, mock_token):
        mock_token.return_value = None
        with patch("sys.argv", ["script", "user", '["org"]', "2026-01-01", "2026-01-07"]):
            assert main() == 1

    def test_exit_1_empty_orgs(self):
        with patch("sys.argv", ["script", "user", "[]", "2026-01-01", "2026-01-07"]):
            assert main() == 1

    def test_exit_1_invalid_date(self):
        with patch("sys.argv", ["script", "user", '["org"]', "not-a-date", "2026-01-07"]):
            assert main() == 1

    def test_exit_1_wrong_arg_count(self):
        with patch("sys.argv", ["script", "user"]):
            assert main() == 1
