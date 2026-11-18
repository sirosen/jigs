# dismisstress

TUI manager for GitHub notifications.

    uv run dismisstress

> [!CAUTION]
> `dismisstress` is published, but is part of
> [@sirosen's jigs](https://github.com/sirosen/jigs).
>
> It is made uniquely for one person's needs, and may or may not suit you.

## Auth

Set `GITHUB_TOKEN` or the app runs `gh auth token` on start.

Security alert counts need a token with the `security_events` scope.

## Keymap

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

## Arguments

`--org ORGNAME,ORGNAME,...` filters the view to specific owners.

    dismisstress --org python,pypa
