import argparse
import contextvars
import dataclasses
import enum
import math
import os
import subprocess
import typing as t
from concurrent.futures import ThreadPoolExecutor

from github import Auth, Github, GithubException
from github.Notification import Notification
from github.PaginatedList import PaginatedList
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Link, Static
from textual.widgets.data_table import ColumnKey


class Filter(enum.Flag):
    MERGED = enum.auto()
    SECURITY = enum.auto()
    REPO = enum.auto()


@dataclasses.dataclass(frozen=True, slots=True)
class CliArgs:
    owners: tuple[str, ...] | None


Row = tuple[Notification, str, str]  # notification, status, url

# token is global (simple)
_GH_TOKEN: str = ""
# PyGithub clients are not thread-safe, so each thread gets its own
_gh_client_var: contextvars.ContextVar[Github | None] = contextvars.ContextVar(
    "gh_client"
)


def _clear_context() -> None:
    _gh_client_var.set(None)


def load_token() -> None:
    global _GH_TOKEN
    _GH_TOKEN = (
        os.environ.get("GITHUB_TOKEN")
        or subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )


def gh_client() -> Github:
    ret: Github | None = _gh_client_var.get(None)
    if ret is None:
        ret = Github(auth=Auth.Token(_GH_TOKEN))
        _gh_client_var.set(ret)
    return ret


def gh_api(verb: str, url: str) -> t.Any:
    return gh_client().requester.requestJsonAndCheck(verb, url)[1]


def subject(notification: Notification) -> tuple[str, str]:
    repo = notification.repository.full_name
    is_security = notification.reason == "security_alert"
    dependabot_uri = f"https://github.com/{repo}/security/dependabot"
    ghsa_uri = f"https://github.com/{repo}/security/advisories"

    if notification.subject.type == "RepositoryAdvisory":
        return "-", ghsa_uri
    if not notification.subject.url and not is_security:
        return "?", ""
    if not notification.subject.url:
        try:
            alerts = gh_api(
                "GET", f"/repos/{repo}/dependabot/alerts?state=open&per_page=100"
            )
        except GithubException:
            return "?", dependabot_uri
        state = f"{len(alerts)}{'+' if len(alerts) == 100 else ''} open"
        return state, dependabot_uri

    try:
        data = gh_api("GET", notification.subject.url)
    except GithubException:
        return "?", ""

    if isinstance(data, list):  # grouped subject, e.g. a thread of Dependabot alerts
        state = (
            ", ".join(
                sorted({x.get("state", "?") for x in data if isinstance(x, dict)})
            )
            or "-"
        )
        return (state, dependabot_uri if is_security else f"https://github.com/{repo}")
    return (
        ("merged" if data.get("merged") else data.get("state", "-")),
        data.get("html_url", ""),
    )


def latest_comment(notification: Notification) -> str:
    if not notification.subject.latest_comment_url:
        return "(no comments)"
    try:
        comment = gh_api("GET", notification.subject.latest_comment_url)
    except GithubException as e:
        return f"(error: {e.status})"
    user = (comment.get("user") or comment.get("author") or {}).get("login", "?")
    return f"{user}:\n\n{comment.get('body') or ''}"


def renderable_comment_thread(notification: Notification) -> RenderableType:
    """Opening post plus the newest 100 main-thread comments, oldest first."""
    if notification.subject.type not in ("Issue", "PullRequest"):
        return Text(latest_comment(notification))

    try:
        subject_info = gh_api("GET", notification.subject.url)
    except GithubException as e:
        return Text(f"(error on notification metadata lookup: {e.status})")

    num_comments = subject_info.get("comments", 0)
    last_page_index = math.ceil(num_comments / 100)
    comments: list[dict[str, t.Any]] = []

    # get the last two pages of comments, then trim down to 100
    # most typically, there are fewer than 100 comments, so this is *usually* one call
    try:
        if last_page_index > 0:
            comments.extend(
                _fetch_page_comments(
                    last_page_index - 1, subject_info["comments_url"]
                )
            )
        comments.extend(
            _fetch_page_comments(last_page_index, subject_info["comments_url"])
        )
    except GithubException as e:
        return Text(f"(error fetching comments: {e.status})")
    comments = comments[-100:]

    # start with the initial comment and optionally a spacer for hidden old comments
    parts: list[RenderableType] = _format_comment(subject_info)
    if (hidden := num_comments - len(comments)) > 0:
        parts.append(Text(f"...{hidden} older comments not shown...\n", "dim"))

    for comment in comments:
        parts.extend(_format_comment(comment))

    return Group(*parts)


def _format_comment(post: dict[str, t.Any]) -> list[RenderableType]:
    parts: list[RenderableType] = []
    user = (post.get("user") or {}).get("login", "ghost")
    parts.append(Text(f"── {user} · {post.get('created_at', '')[:10]}", "bold"))
    parts.append(Padding(Text(post.get("body") or ""), (0, 0, 1, 2)))
    return parts


def _fetch_page_comments(page_index: int, comments_url: str) -> list[dict[str, t.Any]]:
    url = f"{comments_url}?per_page=100&page={page_index}"
    return gh_api("GET", url)  # type: ignore[no-any-return]


def owner(notification: Notification) -> str:
    return notification.repository.full_name.split("/")[0].lower()


def matches_filter(
    filter: Filter, notification: Notification, status: str, repo: str | None
) -> bool:
    return (
        (Filter.MERGED not in filter or status == "merged")
        and (Filter.SECURITY not in filter or notification.reason == "security_alert")
        and (Filter.REPO not in filter or notification.repository.full_name == repo)
    )


class Dismisstress(App[None]):
    CSS = (
        "DataTable { height: 2fr; } VerticalScroll { height: 1fr; border: solid gray; }"
    )
    BINDINGS: t.ClassVar[list[BindingType]] = [
        ("space,x", "select", "Select"),
        ("m", "filter('MERGED')", "Merged only"),
        ("s", "filter('SECURITY')", "Security only"),
        ("o", "filter('REPO')", "This repo only"),
        ("D", "dismiss", "Dismiss"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        Binding("j", "simulate_key('down')", "Down"),
        Binding("k", "simulate_key('up')", "Up"),
        Binding("less_than_sign", "sort(-1)", "Sort prev", key_display="<"),
        Binding("greater_than_sign", "sort(1)", "Sort next", key_display=">"),
    ]

    def __init__(self, args: CliArgs) -> None:
        super().__init__()
        self.owners = args.owners
        self.rows: dict[str, Row] = {}
        self.comments: dict[str, RenderableType] = {}
        self.selected: set[str] = set()
        self.filter = Filter(0)
        self.repo: str | None = None
        self.sort_by: ColumnKey | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")
        yield Link("", id="link")
        with VerticalScroll():
            yield Static(id="detail")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("", key="sel")
        table.add_columns("Unread", "Repo", "Type", "Reason", "Status", "Title")
        self.action_refresh()

    def current(self) -> str | None:
        table = self.query_one(DataTable)
        if table.row_count:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return None

    def render_table(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        for id, (notification, status, _) in self.rows.items():
            if matches_filter(self.filter, notification, status, self.repo):
                table.add_row(
                    "*" if id in self.selected else " ",
                    "●" if notification.unread else " ",
                    notification.repository.full_name,
                    notification.subject.type,
                    notification.reason,
                    status,
                    notification.subject.title,
                    key=id,
                )
        if self.sort_by:
            table.sort(self.sort_by)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        else:
            self.show_detail("", "")
        self.update_sub_title()

    def update_sub_title(self) -> None:
        table = self.query_one(DataTable)
        sort = ""
        if self.sort_by:
            sort = (
                f", sorted by {table.columns[self.sort_by].label.plain or 'Selected'}"
            )
        self.sub_title = f"{table.row_count} shown, {len(self.selected)} selected{sort}"

    @work(thread=True, exclusive=True, group="load")
    def action_refresh(self) -> None:
        self.call_from_thread(setattr, self, "sub_title", "loading...")
        # PyGithub's get_notifications() lacks is_done; this matches the web inbox
        params = {"all": "true", "is_done": "false"}
        ns = list(
            PaginatedList(Notification, gh_client().requester, "/notifications", params)
        )
        if self.owners:
            ns = [n for n in ns if owner(n) in self.owners]
        # reset on init: threads inherit context on free-threaded builds
        with ThreadPoolExecutor(8, initializer=_clear_context) as ex:
            subjects = list(ex.map(subject, ns))
        self.call_from_thread(
            self.loaded, {n.id: (n, *s) for n, s in zip(ns, subjects)}
        )

    def loaded(self, rows: dict[str, Row]) -> None:
        self.rows = rows
        self.comments = {}
        self.selected &= rows.keys()
        self.render_table()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        self.sort_by = event.column_key
        self.render_table()

    def action_sort(self, step: int) -> None:
        cols: list[ColumnKey | None] = [None, *self.query_one(DataTable).columns]
        self.sort_by = cols[(cols.index(self.sort_by) + step) % len(cols)]
        self.render_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value is not None:
            self.show(event.row_key.value)

    @work(thread=True, exclusive=True, group="detail")
    def show(self, id: str) -> None:
        n, s, url = self.rows[id]
        if id not in self.comments:
            self.comments[id] = renderable_comment_thread(n)
        header = Text(f"{n.subject.title}\n{n.subject.type}: {s}\n", "bold")
        if self.current() == id:
            self.call_from_thread(
                self.show_detail, url, Group(header, self.comments[id])
            )

    def show_detail(self, url: str, text: RenderableType) -> None:
        link = self.query_one(Link)
        link.text = link.url = url
        self.query_one("#detail", Static).update(text)
        self.call_after_refresh(
            self.query_one(VerticalScroll).scroll_end, animate=False
        )

    def action_select(self) -> None:
        if (id := self.current()) is None:
            return
        self.selected ^= {id}
        self.query_one(DataTable).update_cell(
            id, "sel", "*" if id in self.selected else ""
        )
        self.update_sub_title()

    def action_filter(self, name: str) -> None:
        kind = Filter[name]
        self.filter ^= kind
        if kind is Filter.REPO and kind in self.filter and (id := self.current()):
            self.repo = self.rows[id][0].repository.full_name
        self.render_table()

    def action_dismiss(self) -> None:
        ids = set(self.selected) or {id for id in [self.current()] if id is not None}
        if ids:
            self.dismiss(ids)

    @work(thread=True, group="dismiss")
    def dismiss(self, ids: set[str]) -> None:
        done = set()
        for i, id in enumerate(ids, 1):
            self.call_from_thread(self.set_status, f"dismissing {i}/{len(ids)}...")
            try:
                gh_api("DELETE", self.rows[id][0].url)
                done.add(id)
            except GithubException as e:
                self.call_from_thread(
                    self.notify, f"dismiss failed: {e.status}", severity="error"
                )
        self.call_from_thread(self.set_status, f"dismissed {len(done)}/{len(ids)}")
        self.call_from_thread(self.dismissed, done)

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def dismissed(self, ids: set[str]) -> None:
        for id in ids:
            self.rows.pop(id, None)
        self.selected -= ids
        self.render_table()


def parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(prog="dismisstress")
    parser.add_argument(
        "--owner",
        "--org",
        dest="owners",
        help="only show these owners (comma-separated, or may be used multiple times)",
        action="append",
        default=[],
    )
    args = parser.parse_args()
    owners = {o.strip().lower() for x in args.owners for o in x.split(",")}
    return CliArgs(owners=tuple(owners) if owners else None)


def main() -> None:
    args = parse_args()
    load_token()
    Dismisstress(args).run()


if __name__ == "__main__":
    main()
