"""Unit tests for weekly_recap/fetchers/fetch_jira.py."""

import json
import os
import subprocess
import sys

import pytest
from unittest.mock import patch, MagicMock

from weekly_recap.fetchers.fetch_jira import (
    validate_inputs,
    validate_date,
    build_jql_queries,
    normalize_issue,
    normalize_acli_output,
    deduplicate_issues,
)


class TestValidateDate:
    """Tests for date validation."""

    def test_valid_date(self):
        assert validate_date("2026-05-07") is True

    def test_invalid_format(self):
        assert validate_date("05-07-2026") is False

    def test_invalid_date(self):
        assert validate_date("2026-13-01") is False

    def test_empty_string(self):
        assert validate_date("") is False

    def test_not_a_date(self):
        assert validate_date("not-a-date") is False


class TestValidateInputs:
    """Tests for input validation."""

    def test_valid_inputs(self):
        result = validate_inputs("user@example.com", ["AWS", "CPS"], "2026-05-01", "2026-05-07")
        assert result is None

    def test_empty_username(self):
        result = validate_inputs("", ["AWS"], "2026-05-01", "2026-05-07")
        assert "jira_username" in result

    def test_whitespace_username(self):
        result = validate_inputs("   ", ["AWS"], "2026-05-01", "2026-05-07")
        assert "jira_username" in result

    def test_empty_projects(self):
        result = validate_inputs("user@example.com", [], "2026-05-01", "2026-05-07")
        assert "at least one project" in result

    def test_too_many_projects(self):
        projects = [f"PROJ{i}" for i in range(11)]
        result = validate_inputs("user@example.com", projects, "2026-05-01", "2026-05-07")
        assert "maximum 10" in result

    def test_invalid_project_entry(self):
        result = validate_inputs("user@example.com", ["AWS", ""], "2026-05-01", "2026-05-07")
        assert "projects[1]" in result

    def test_invalid_start_date(self):
        result = validate_inputs("user@example.com", ["AWS"], "not-a-date", "2026-05-07")
        assert "start_date" in result

    def test_invalid_end_date(self):
        result = validate_inputs("user@example.com", ["AWS"], "2026-05-01", "invalid")
        assert "end_date" in result

    def test_projects_not_a_list(self):
        result = validate_inputs("user@example.com", "AWS", "2026-05-01", "2026-05-07")
        assert "JSON array" in result


class TestBuildJqlQueries:
    """Tests for JQL query construction."""

    def test_produces_3_queries(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        assert len(queries) == 4

    def test_query_1_assigned(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        q1 = queries[0]
        assert 'assignee = "user@test.com"' in q1
        assert 'project = "CPS"' in q1
        assert 'updated >= "2026-05-01"' in q1
        assert 'updated < "2026-05-08"' in q1

    def test_query_2_was_during(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        q2 = queries[1]
        assert 'assignee WAS "user@test.com" DURING ("2026-05-01", "2026-05-07")' in q2
        assert 'assignee != "user@test.com"' in q2
        assert 'project = "CPS"' in q2

    def test_query_3_reporter(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        q3 = queries[2]
        assert 'reporter = "user@test.com"' in q3
        assert 'project = "CPS"' in q3
        assert 'updated >= "2026-05-01"' in q3
        assert 'updated < "2026-05-08"' in q3

    def test_query_4_stale_assigned(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        q4 = queries[3]
        assert 'assignee = "user@test.com"' in q4
        assert 'project = "CPS"' in q4
        assert 'status NOT IN (Done, Closed, Resolved, Cancelled, Rejected, Declined)' in q4
        assert 'updated < "2026-05-01"' in q4

    def test_aws_subtask_exclusion(self):
        queries = build_jql_queries("user@test.com", "AWS", "2026-05-01", "2026-05-07", "2026-05-08")
        for q in queries:
            assert "AND issuetype not in subTaskIssueTypes()" in q

    def test_non_aws_no_subtask_exclusion(self):
        queries = build_jql_queries("user@test.com", "CPS", "2026-05-01", "2026-05-07", "2026-05-08")
        for q in queries:
            assert "subTaskIssueTypes" not in q

    def test_aws_case_insensitive(self):
        """AWS check should be case-insensitive."""
        queries = build_jql_queries("user@test.com", "aws", "2026-05-01", "2026-05-07", "2026-05-08")
        for q in queries:
            assert "AND issuetype not in subTaskIssueTypes()" in q


class TestNormalizeIssue:
    """Tests for issue normalization."""

    def test_flat_structure(self):
        raw = {
            "key": "AWS-123",
            "summary": "Fix bug",
            "status": "In Progress",
            "duedate": "2026-06-01",
            "customfield_11674": None,
            "assignee": "John Doe",
            "reporter": "Jane Smith",
        }
        result = normalize_issue(raw)
        assert result["key"] == "AWS-123"
        assert result["summary"] == "Fix bug"
        assert result["status"] == "In Progress"
        assert result["duedate"] == "2026-06-01"
        assert result["assignee"] == "John Doe"
        assert result["reporter"] == "Jane Smith"

    def test_nested_fields_structure(self):
        raw = {
            "key": "CPS-456",
            "fields": {
                "summary": "Deploy service",
                "status": {"name": "Done"},
                "duedate": "2026-05-15",
                "customfield_11674": "2026-06-01",
                "assignee": {"displayName": "Alice", "name": "alice"},
                "reporter": {"displayName": "Bob", "name": "bob"},
            },
        }
        result = normalize_issue(raw)
        assert result["key"] == "CPS-456"
        assert result["summary"] == "Deploy service"
        assert result["status"] == "Done"
        assert result["duedate"] == "2026-05-15"
        assert result["customfield_11674"] == "2026-06-01"
        assert result["assignee"] == "Alice"
        assert result["reporter"] == "Bob"

    def test_null_assignee_reporter(self):
        raw = {
            "key": "AWS-789",
            "summary": "Unassigned task",
            "status": "To Do",
            "duedate": None,
            "customfield_11674": None,
            "assignee": None,
            "reporter": None,
        }
        result = normalize_issue(raw)
        assert result["assignee"] is None
        assert result["reporter"] is None
        assert result["duedate"] is None


class TestNormalizeAcliOutput:
    """Tests for acli output normalization."""

    def test_list_of_issues(self):
        data = [
            {"key": "AWS-1", "summary": "Task 1", "status": "Done", "duedate": None,
             "customfield_11674": None, "assignee": "A", "reporter": "B"},
            {"key": "AWS-2", "summary": "Task 2", "status": "Open", "duedate": None,
             "customfield_11674": None, "assignee": "C", "reporter": "D"},
        ]
        result = normalize_acli_output(data)
        assert len(result) == 2
        assert result[0]["key"] == "AWS-1"
        assert result[1]["key"] == "AWS-2"

    def test_dict_with_issues_key(self):
        data = {
            "issues": [
                {"key": "CPS-1", "summary": "Issue", "status": "Open", "duedate": None,
                 "customfield_11674": None, "assignee": None, "reporter": None},
            ]
        }
        result = normalize_acli_output(data)
        assert len(result) == 1
        assert result[0]["key"] == "CPS-1"

    def test_single_issue_dict(self):
        data = {"key": "AWS-99", "summary": "Single", "status": "Done", "duedate": None,
                "customfield_11674": None, "assignee": None, "reporter": None}
        result = normalize_acli_output(data)
        assert len(result) == 1
        assert result[0]["key"] == "AWS-99"

    def test_empty_list(self):
        result = normalize_acli_output([])
        assert result == []

    def test_unexpected_structure(self):
        result = normalize_acli_output("not a list or dict")
        assert result == []


class TestDeduplicateIssues:
    """Tests for issue deduplication."""

    def test_no_duplicates(self):
        issues = [
            {"key": "AWS-1", "summary": "A"},
            {"key": "AWS-2", "summary": "B"},
        ]
        result = deduplicate_issues(issues)
        assert len(result) == 2

    def test_removes_duplicates(self):
        issues = [
            {"key": "AWS-1", "summary": "First"},
            {"key": "AWS-1", "summary": "Duplicate"},
            {"key": "AWS-2", "summary": "Other"},
        ]
        result = deduplicate_issues(issues)
        assert len(result) == 2
        assert result[0]["summary"] == "First"  # keeps first occurrence

    def test_empty_list(self):
        result = deduplicate_issues([])
        assert result == []

    def test_all_duplicates(self):
        issues = [
            {"key": "AWS-1", "summary": "A"},
            {"key": "AWS-1", "summary": "B"},
            {"key": "AWS-1", "summary": "C"},
        ]
        result = deduplicate_issues(issues)
        assert len(result) == 1
        assert result[0]["summary"] == "A"


class TestMainExitCodes:
    """Tests for main() exit codes via subprocess."""

    def test_missing_args_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "weekly_recap.fetchers.fetch_jira"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 1

    def test_invalid_json_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "weekly_recap.fetchers.fetch_jira", "user", "not-json", "2026-05-01", "2026-05-07"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 1

    def test_empty_projects_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "weekly_recap.fetchers.fetch_jira", "user", "[]", "2026-05-01", "2026-05-07"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 1

    def test_invalid_date_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "weekly_recap.fetchers.fetch_jira", "user", '["AWS"]', "bad-date", "2026-05-07"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 1

    def test_empty_username_exits_1(self):
        result = subprocess.run(
            [sys.executable, "-m", "weekly_recap.fetchers.fetch_jira", "", '["AWS"]', "2026-05-01", "2026-05-07"],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 1
