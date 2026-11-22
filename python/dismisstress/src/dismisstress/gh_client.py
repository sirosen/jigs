"""A GitHub API client."""
import os
import subprocess
import typing as t

import aiohttp

from .data_models import APIResponse, GHNotification

T = t.TypeVar("T")


def _load_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or (
        subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )


def _new_session(token: str) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )


async def _parse_api_response(response: aiohttp.ClientResponse) -> APIResponse:
    response.raise_for_status()
    data = await response.json()
    if next_link_header := response.links.get("next"):
        next_link = str(next_link_header.get("url"))
    else:
        next_link = None
    return APIResponse(data, next_link)


class GithubClient:
    """
    GitHub Client class.

    Automatically handles authentication synchronously on init.
    """

    API = "https://api.github.com"

    def __init__(self) -> None:
        self._token = _load_token()
        self._session = _new_session(self._token)

    async def close(self) -> None:
        await self._session.close()

    async def request(
        self, verb: str, url: str, **params: t.Any
    ) -> APIResponse:
        if url.startswith("/"):
            url = self.API + url
        async with self._session.request(
            verb, url, params=params, timeout=aiohttp.ClientTimeout(30)
        ) as response:
            return await _parse_api_response(response)

    async def get(self, url: str, **params: t.Any) -> APIResponse:
        return await self.request("GET", url, **params)

    async def delete(self, url: str, **params: t.Any) -> APIResponse:
        return await self.request("DELETE", url, **params)

    async def paginated_get(
        self, url: str, per_page: int = 100, **params: t.Any
    ) -> t.AsyncIterator[APIResponse]:
        """
        GET every page, following Link headers.
        Does not return/yield said link headers.

        Assumes that the underlying data is a list by type (but doesn't check).
        """
        response = await self.get(url, per_page=per_page, **params)
        yield response
        while response.next_link:
            response = await self.get(response.next_link)
            yield response

    async def list_notifications(self) -> list[GHNotification]:
        # is_done=false matches the web inbox (read and unread, not done)
        results = []
        async for page in self.paginated_get(
            "/notifications", all="true", is_done="false"
        ):
            results.extend([GHNotification.from_json(item) for item in page.json_body])
        return results

    async def get_dependabot_alerts(
        self, repo: str, state: str = "open", per_page: int = 100
    ) -> t.Any:
        return await self.get(
            f"/repos/{repo}/dependabot/alerts", state=state, per_page=per_page
        )

    async def clear_notification(self, notification: GHNotification) -> None:
        await self.delete(notification.url)
