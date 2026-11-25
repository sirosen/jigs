"""A GitHub API client."""

import asyncio
import math
import os
import subprocess
import typing as t

import aiohttp

from .data_models import (
    APIResponse,
    GHComment,
    GHCommentThread,
    GHNotification,
    GHReview,
    GHReviewComment,
    GHReviewThread,
)

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
        },
        # The "connector" controls the session's connection pooling, so a modest pool
        # size limits how hard we hit the GitHub API and avoids rate limiting.
        # The documented limit for concurrent requests is 100. see:
        #   https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
        connector=aiohttp.TCPConnector(limit=64),
    )


async def _parse_api_response(response: aiohttp.ClientResponse) -> APIResponse:
    response.raise_for_status()
    try:
        data = await response.json(encoding="utf-8")
    except aiohttp.ClientResponseError:
        data = None

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

    async def request(self, verb: str, url: str, **params: t.Any) -> APIResponse:
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

    async def get_all(self, url: str, **params: t.Any) -> list[t.Any]:
        return [
            x
            async for page in self.paginated_get(url, **params)
            for x in page.json_body
        ]

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
    ) -> APIResponse:
        return await self.get(
            f"/repos/{repo}/dependabot/alerts", state=state, per_page=per_page
        )

    async def get_comment(self, url: str) -> GHComment:
        return GHComment.from_json((await self.get(url)).json_body)

    async def get_comment_thread(self, url: str) -> GHCommentThread:
        """An issue or PR's opening post plus its newest 100 comments, oldest first."""
        issue = (await self.get(url)).json_body
        last_page = math.ceil(issue.get("comments", 0) / 100)
        comments = []
        for page in (last_page - 1, last_page):  # the newest 100 span <=2 pages
            if page > 0:
                response = await self.get(
                    issue["comments_url"], per_page=100, page=page
                )
                comments.extend(response.json_body)
        return GHCommentThread.from_json(issue, comments[-100:])

    async def get_reviews(self, pull_url: str) -> list[GHReview]:
        """A PR's reviews, oldest first, each with the line comment threads it began."""
        reviews, comments = await asyncio.gather(
            self.get_all(f"{pull_url}/reviews"), self.get_all(f"{pull_url}/comments")
        )
        # replies all point at the first comment of their thread
        comment_chains: dict[int, list[GHReviewComment]] = {}
        for c in comments:
            gh_comment = GHReviewComment.from_json(c)
            comment_chains.setdefault(gh_comment.thread_key, []).append(gh_comment)

        threads: dict[int | None, list[GHReviewThread]] = {}
        for chain in comment_chains.values():
            threads.setdefault(chain[0].review_id, []).append(
                GHReviewThread.from_review_comments(chain)
            )

        return [GHReview.from_json(r, tuple(threads.get(r["id"], []))) for r in reviews]

    async def clear_notification(self, notification: GHNotification) -> None:
        await self.delete(notification.url)
