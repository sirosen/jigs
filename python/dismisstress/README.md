# dismisstress

TUI manager for GitHub notifications.

    uv run dismisstress

Auth: `GITHUB_TOKEN`, else `gh auth token`.

Keys:
|key        |action                       |
|-----------|-----------------------------|
|`space`/`x`|select                       |
|`D`        |dismiss selected (or current)|
|`m`        |filter:merged-only           |
|`s`        |filter:security-only         |
|`o`        |filter:highlighted repo only |
|`r`        |refresh                      |
|`j`/`k`    |down/up                      |
|`<`/`>`    |previous/next sort column    |
|`q`        |quit                         |

Clicking a column header also sorts by it.

Security alert counts need a token with the `security_events` scope.
