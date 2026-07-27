"""CLI entry point for the weekly-recap command."""

import sys


def main() -> None:
    """CLI entry point registered in pyproject.toml."""
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print_usage()
        sys.exit(0)

    subcommand = args[0]

    if subcommand == "preflight":
        from weekly_recap.preflight import main as preflight_main

        sys.exit(preflight_main())

    elif subcommand == "generate":
        # Pass remaining args to run_recap which parses dates from sys.argv
        sys.argv = ["weekly-recap-generate"] + args[1:]
        from weekly_recap.run_recap import main as generate_main

        generate_main()

    elif subcommand == "fetch-comments":
        from weekly_recap.fetchers.fetch_jira_comments import main as comments_main

        comments_main()

    elif subcommand == "fetch-subtasks":
        from weekly_recap.fetchers.fetch_jira_subtasks import main as subtasks_main

        subtasks_main()

    elif subcommand == "fetch-history":
        from weekly_recap.fetchers.fetch_jira_history import main as history_main

        history_main()

    elif subcommand == "fetch-details":
        # Run all three detail fetchers: comments, subtasks, history
        print("▶ Fetching detailed ticket data (comments, subtasks, history)...")
        print()

        from weekly_recap.fetchers.fetch_jira_comments import main as comments_main
        from weekly_recap.fetchers.fetch_jira_subtasks import main as subtasks_main
        from weekly_recap.fetchers.fetch_jira_history import main as history_main

        exit_codes = []

        print("── Comments ──")
        try:
            comments_main()
        except SystemExit as e:
            exit_codes.append(e.code or 0)
        print()

        print("── Subtasks ──")
        try:
            subtasks_main()
        except SystemExit as e:
            exit_codes.append(e.code or 0)
        print()

        print("── History ──")
        try:
            history_main()
        except SystemExit as e:
            exit_codes.append(e.code or 0)
        print()

        if any(code == 1 for code in exit_codes):
            sys.exit(1)
        elif any(code == 2 for code in exit_codes):
            sys.exit(2)
        print("✅ All detail data fetched successfully.")
        sys.exit(0)

    else:
        print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
        print_usage()
        sys.exit(1)


def print_usage() -> None:
    """Print CLI usage information."""
    print("Usage: weekly-recap <command> [options]")
    print()
    print("Commands:")
    print("  preflight              Validate environment readiness")
    print("  generate [start] [end] Generate weekly recap report")
    print("  fetch-details          Fetch comments, subtasks & history for cached tickets")
    print("  fetch-comments         Fetch Jira comments only")
    print("  fetch-subtasks         Fetch Jira subtasks only")
    print("  fetch-history          Fetch Jira changelog/history only")
    print()
    print("Examples:")
    print("  weekly-recap preflight")
    print("  weekly-recap generate")
    print("  weekly-recap generate 2026-05-09 2026-05-15")
    print("  weekly-recap fetch-details")


if __name__ == "__main__":
    main()
