import asyncio
import typing as t

import aiohttp
from rich.console import Group, RenderableType
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Link, Static
from textual.widgets.data_table import ColumnKey

from .data_models import CliArgs, Filter, GHNotification, Row
from .formatters import format_comment_thread, format_review_list
from .gh_client import GithubClient


class Dismisstress(App[None]):
    CSS = """
    DataTable {
        height: 1fr;
    }
    VerticalScroll {
        height: 1fr;
        border: solid gray;
    }
    VerticalScroll:focus {
        border: solid $accent;
    }
    """
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

    def __init__(self, args: CliArgs, client: GithubClient) -> None:
        super().__init__()
        self.client = client
        self.owners = args.owners
        self.rows: dict[str, Row] = {}
        self.comments: dict[str, RenderableType] = {}
        self.reviews: dict[str, RenderableType | None] = {}
        self.selected: set[str] = set()
        self.filter = Filter(0)
        self.repo: str | None = None
        self.sort_by: ColumnKey | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(cursor_type="row")
        yield Link("", id="link")
        with VerticalScroll() as main_comment_thread:
            main_comment_thread.border_title = "Comments"
            yield Static(id="detail")
        with VerticalScroll(id="reviews-pane") as reviews:
            reviews.border_title = "Reviews"
            yield Static(id="reviews")
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
        cursor_row = table.cursor_row
        table.clear()
        for row in self.rows.values():
            if row.matches_filter(self.filter, self.repo):
                table.add_row(
                    "*" if row.notification.id in self.selected else " ",
                    "●" if row.notification.unread else " ",
                    row.notification.repo,
                    row.notification.subject.type,
                    row.notification.reason,
                    row.status,
                    row.notification.subject.title,
                    key=row.notification.id,
                )
        if self.sort_by:
            table.sort(self.sort_by)
        if table.row_count:
            table.move_cursor(row=min(cursor_row, table.row_count - 1))
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

    @work(exclusive=True, group="load")
    async def action_refresh(self) -> None:
        self.sub_title = "loading..."
        notifications = await self.client.list_notifications()
        if self.owners:
            notifications = [n for n in notifications if n.owner in self.owners]
        rows = await asyncio.gather(
            *(notification2row(self.client, n) for n in notifications)
        )

        self.rows = {row.notification.id: row for row in rows}
        self.comments = {}
        self.reviews = {}
        self.selected &= self.rows.keys()
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

    @work(exclusive=True, group="detail")
    async def show(self, id: str) -> None:
        row = self.rows[id]
        if id not in self.comments:
            self.comments[id], self.reviews[id] = await asyncio.gather(
                renderable_comment_thread(self.client, row.notification),
                renderable_reviews(self.client, row.notification),
            )
        header = Text(
            (
                f"{row.notification.subject.title}\n"
                f"{row.notification.subject.type}: {row.status}\n"
            ),
            "bold",
        )
        if self.current() == id:
            self.show_detail(
                row.url, Group(header, self.comments[id]), self.reviews[id]
            )

    def show_detail(
        self, url: str, text: RenderableType, reviews: RenderableType | None = None
    ) -> None:
        link = self.query_one(Link)
        link.text = link.url = url
        self.query_one("#detail", Static).update(text)
        self.query_one("#reviews", Static).update(reviews or "")
        self.query_one("#reviews-pane").display = reviews is not None
        for pane in self.query(VerticalScroll):
            self.call_after_refresh(pane.scroll_end, animate=False)

    def action_select(self) -> None:
        if (id := self.current()) is None:
            return
        self.selected ^= {id}
        self.query_one(DataTable).update_cell(
            id, "sel", "*" if id in self.selected else " "
        )
        self.update_sub_title()

    def action_filter(self, name: str) -> None:
        kind = Filter[name]
        self.filter ^= kind
        if kind is Filter.REPO and kind in self.filter and (id := self.current()):
            self.repo = self.rows[id].notification.repo
        self.render_table()

    async def action_dismiss(self) -> None:
        ids = set(self.selected) or {id for id in [self.current()] if id is not None}
        if ids:
            self.dismiss(ids)

    @work(group="dismiss")
    async def dismiss(self, ids: set[str]) -> None:
        done = set()
        for i, id in enumerate(ids, 1):
            self.set_status(f"dismissing {i}/{len(ids)}...")
            if i > 1:
                await asyncio.sleep(1)  # GitHub asks for >=1s between mutating requests
            try:
                await self.client.clear_notification(self.rows[id].notification)
                done.add(id)
            except aiohttp.ClientResponseError as e:
                self.notify(f"dismiss failed: {e}", severity="error")
        self.set_status(f"dismissed {len(done)}/{len(ids)}")
        self.mark_dismissed(done)

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(text)

    def mark_dismissed(self, ids: set[str]) -> None:
        for id in ids:
            self.rows.pop(id, None)
        self.selected -= ids
        self.render_table()


async def notification2row(gh: GithubClient, notification: GHNotification) -> Row:
    repo = notification.repo
    url = notification.subject.url
    dependabot_uri = f"https://github.com/{repo}/security/dependabot"
    ghsa_uri = f"https://github.com/{repo}/security/advisories"

    if notification.subject.type == "RepositoryAdvisory":
        return Row(notification, "-", ghsa_uri)
    if not url and not notification.is_security_alert:
        return Row(notification, "?", "")
    if not url:
        try:
            alerts = (await gh.get_dependabot_alerts(repo)).json_body
        except aiohttp.ClientResponseError:
            return Row(notification, "?", dependabot_uri)
        state = f"{len(alerts)}{'+' if len(alerts) == 100 else ''} open"
        return Row(notification, state, dependabot_uri)

    try:
        data = (await gh.get(url)).json_body
    except aiohttp.ClientResponseError:
        return Row(notification, "?", "")

    if isinstance(data, list):  # grouped subject, e.g. a thread of Dependabot alerts
        state = (
            ", ".join(
                sorted({x.get("state", "?") for x in data if isinstance(x, dict)})
            )
            or "-"
        )
        return Row(
            notification,
            state,
            dependabot_uri
            if notification.is_security_alert
            else f"https://github.com/{repo}",
        )
    return Row(
        notification,
        ("merged" if data.get("merged") else data.get("state", "-")),
        data.get("html_url", ""),
    )


async def latest_comment(gh: GithubClient, notification: GHNotification) -> str:
    if not (url := notification.subject.latest_comment_url):
        return "(no comments)"
    try:
        comment = await gh.get_comment(url)
    except aiohttp.ClientResponseError as e:
        return f"(error: {e})"
    return f"{comment.user}:\n\n{comment.body}"


async def renderable_comment_thread(
    gh: GithubClient, notification: GHNotification
) -> RenderableType:
    """Opening post plus the newest 100 main-thread comments, oldest first."""
    url = notification.subject.url
    if not url:
        return Text("(no comments)")
    if notification.subject.type == "Discussion":
        return Text("(... TODO: no support yet for discussion threads ...)")
    elif notification.subject.type not in ("Issue", "PullRequest"):
        return Text(await latest_comment(gh, notification))

    try:
        thread = await gh.get_comment_thread(url)
    except aiohttp.ClientResponseError as e:
        return Text(f"(error fetching comments: {e})")

    return format_comment_thread(thread)


async def renderable_reviews(
    gh: GithubClient, notification: GHNotification
) -> RenderableType | None:
    """PR reviews, oldest first, each with its inline threads. None if no reviews."""
    url = notification.subject.url
    if notification.subject.type != "PullRequest" or not url:
        return None
    try:
        reviews = await gh.get_reviews(url)
    except aiohttp.ClientResponseError as e:
        return Text(f"(error fetching reviews: {e})")

    return format_review_list(reviews)
