"""A GitHub API client."""
import os
import subprocess
import threading
import typing as t

import requests

from .data_models import GHNotification


def _load_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or (
        subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )


class GithubClient:
    """
    Thread-safe client: one connection per thread.

    Automatically handles authentication on init.
    """

    API = "https://api.github.com"

    def __init__(self) -> None:
        self._token = _load_token()
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.headers.update(
                {
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
            self._local.session = session
        return self._local.session  # type: ignore[return-value]

    def request(self, verb: str, url: str, **params: t.Any) -> requests.Response:
        if url.startswith("/"):
            url = self.API + url
        response = self._session().request(verb, url, params=params, timeout=30)
        response.raise_for_status()
        return response

    def get(self, url: str, **params: t.Any) -> t.Any:
        return self.request("GET", url, **params).json()

    def delete(self, url: str, **params: t.Any) -> t.Any:
        return self.request("DELETE", url, **params).json()

    def paginated_get(
        self, url: str, per_page: int = 100, **params: t.Any
    ) -> t.Iterator[list[t.Any]]:
        """
        GET every page, following Link headers.

        Assumes that the underlying data is a list by type (but doesn't check).
        """
        response = self.request("GET", url, per_page=per_page, **params)
        yield response.json()
        while "next" in response.links:
            response = self.request("GET", response.links["next"]["url"])
            yield response.json()

    def list_notifications(self) -> list[GHNotification]:
        # is_done=false matches the web inbox (read and unread, not done)
        pages = list(self.paginated_get("/notifications", all="true", is_done="false"))
        return [GHNotification.from_json(item) for page in pages for item in page]

    def get_dependabot_alerts(
        self, repo: str, state: str = "open", per_page: int = 100
    ) -> t.Any:
        return self.get(
            f"/repos/{repo}/dependabot/alerts", state=state, per_page=per_page
        )

    def clear_notification(self, notification: GHNotification) -> None:
        self.delete(notification.url)
