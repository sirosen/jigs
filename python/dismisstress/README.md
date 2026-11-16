# dismisstress

TUI manager for GitHub notifications.

    uv run dismisstress

Auth: `GITHUB_TOKEN`, else `gh auth token`.

Keys: `space` select, `m` toggle merged-only, `s` toggle security-only, `d` dismiss selected (or current), `r` refresh, `j`/`k` down/up, `q` quit.

Security alert counts need a token with the `security_events` scope.
