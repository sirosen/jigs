import contextvars
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from github import Auth, Github, GithubException
from rich.text import Text
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Footer, Header, Link, Static

# token is global (simple)
_GH_TOKEN: str = ""
# PyGithub clients are not thread-safe, so each thread gets its own
_gh_client_var: contextvars.ContextVar[Github] = contextvars.ContextVar("gh_client")


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


def gh_api(verb, url):
    return gh_client().requester.requestJsonAndCheck(verb, url)[1]


def subject(n):
    if not n.subject.url:
        return "-", ""
    try:
        d = gh_api("GET", n.subject.url)
    except GithubException:
        return "?", ""
    return ("merged" if d.get("merged") else d.get("state", "-")), d.get("html_url", "")


def latest_comment(n):
    if not n.subject.latest_comment_url:
        return "(no comments)"
    try:
        c = gh_api("GET", n.subject.latest_comment_url)
    except GithubException as e:
        return f"(error: {e.status})"
    user = (c.get("user") or c.get("author") or {}).get("login", "?")
    return f"{user}:\n\n{c.get('body') or ''}"


class Dismisstress(App):
    CSS = (
        "DataTable { height: 2fr; } VerticalScroll { height: 1fr; border: solid gray; }"
    )
    BINDINGS = (
        ("space", "toggle", "Select"),
        ("a", "select_all", "Select all"),
        ("m", "merged", "Merged only"),
        ("d", "dismiss", "Dismiss"),
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        Binding("j", "key('down')", "Down"),
        Binding("k", "key('up')", "Up"),
    )

    def __init__(self):
        super().__init__()
        self.rows = {}  # id -> (notification, status, url)
        self.comments = {}
        self.selected = set()
        self.merged_only = False

    def compose(self):
        yield Header()
        yield DataTable(cursor_type="row")
        with VerticalScroll():
            yield Link("", id="link")
            yield Static(id="detail")
        yield Footer()

    def on_mount(self):
        t = self.query_one(DataTable)
        t.add_column("", key="sel")
        t.add_columns("Unread", "Repo", "Type", "Reason", "Status", "Title")
        self.action_refresh()

    def current(self):
        t = self.query_one(DataTable)
        if t.row_count:
            return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value

    def render_table(self):
        t = self.query_one(DataTable)
        row = t.cursor_row
        t.clear()
        for id, (n, s, _) in self.rows.items():
            if not self.merged_only or s == "merged":
                t.add_row(
                    "*" if id in self.selected else "",
                    "●" if n.unread else "",
                    n.repository.full_name,
                    n.subject.type,
                    n.reason,
                    s,
                    n.subject.title,
                    key=id,
                )
        if t.row_count:
            t.move_cursor(row=min(row, t.row_count - 1))
        else:
            self.show_detail("", "")
        self.sub_title = f"{t.row_count} shown, {len(self.selected)} selected"

    @work(thread=True, exclusive=True, group="load")
    def action_refresh(self):
        self.call_from_thread(setattr, self, "sub_title", "loading...")
        ns = list(gh_client().get_user().get_notifications(all=True))
        with ThreadPoolExecutor(8) as ex:
            subjects = list(ex.map(subject, ns))
        self.call_from_thread(
            self.loaded, {n.id: (n, *s) for n, s in zip(ns, subjects)}
        )

    def loaded(self, rows):
        self.rows = rows
        self.comments = {}
        self.selected &= rows.keys()
        self.render_table()

    def on_data_table_row_highlighted(self, event):
        self.show(event.row_key.value)

    @work(thread=True, exclusive=True, group="detail")
    def show(self, id):
        n, s, url = self.rows[id]
        if id not in self.comments:
            self.comments[id] = latest_comment(n)
        text = Text(f"{n.subject.title}\n{n.subject.type}: {s}\n\n", style="bold")
        text.append(self.comments[id])
        if self.current() == id:
            self.call_from_thread(self.show_detail, url, text)

    def show_detail(self, url, text):
        link = self.query_one(Link)
        link.text = link.url = url
        self.query_one("#detail", Static).update(text)

    def action_key(self, key):
        self.simulate_key(key)

    def action_toggle(self):
        if (id := self.current()) is None:
            return
        self.selected ^= {id}
        self.query_one(DataTable).update_cell(
            id, "sel", "*" if id in self.selected else ""
        )
        self.sub_title = (
            f"{self.query_one(DataTable).row_count} shown, "
            f"{len(self.selected)} selected"
        )

    def action_select_all(self):
        self.selected |= {r.value for r in self.query_one(DataTable).rows}
        self.render_table()

    def action_merged(self):
        self.merged_only = not self.merged_only
        self.render_table()

    def action_dismiss(self):
        ids = self.selected or {self.current()} - {None}
        if ids:
            self.dismiss(ids)

    @work(thread=True, group="dismiss")
    def dismiss(self, ids):
        done = set()
        for id in ids:
            try:
                gh_api("DELETE", self.rows[id][0].url)
                done.add(id)
            except GithubException as e:
                self.call_from_thread(
                    self.notify, f"dismiss failed: {e.status}", severity="error"
                )
        self.call_from_thread(self.dismissed, done)

    def dismissed(self, ids):
        for id in ids:
            self.rows.pop(id, None)
        self.selected -= ids
        self.render_table()


def main():
    load_token()
    Dismisstress().run()


if __name__ == "__main__":
    main()
