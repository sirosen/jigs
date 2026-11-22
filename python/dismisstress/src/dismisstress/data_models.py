"""
Models for internal and external datatypes.

Covers GitHub API data, user input data, and internal state.
"""
from __future__ import annotations

import dataclasses
import enum
import typing as t


class Filter(enum.Flag):
    MERGED = enum.auto()
    SECURITY = enum.auto()
    REPO = enum.auto()


@dataclasses.dataclass(frozen=True, slots=True)
class CliArgs:
    owners: tuple[str, ...] | None


@dataclasses.dataclass(frozen=True, slots=True)
class APIResponse:
    # we don't know the type in the general case -- could be a dict or a list
    # at the very least
    json_body: t.Any
    next_link: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class GHNotificationSubject:
    title: str
    type: str
    url: str | None
    latest_comment_url: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class GHNotification:  # the fields we use from GET /notifications
    id: str
    unread: bool
    reason: str
    url: str
    owner: str
    repo: str  # owner/name
    subject: GHNotificationSubject

    @property
    def is_security_alert(self) -> bool:
        return bool(self.reason == "security_alert")

    @classmethod
    def from_json(cls, data: dict[str, t.Any]) -> GHNotification:
        s = data["subject"]
        return cls(
            id=data["id"],
            unread=data["unread"],
            reason=data["reason"],
            url=data["url"],
            owner=data["repository"]["owner"]["login"],
            repo=data["repository"]["full_name"],
            subject=GHNotificationSubject(
                s["title"], s["type"], s["url"], s["latest_comment_url"]
            ),
        )


# a comment as modeled for passing into presentation
# does not necessarily correspond with any GitHub APIs
@dataclasses.dataclass(frozen=True, slots=True)
class Comment:
    user: str
    created_at: str | None
    body: None

    @classmethod
    def from_json(cls, data: dict[str, t.Any]) -> t.Self:
        return cls(
            user=cls._get_username(data),
            created_at=data.get("created_at"),
            body=data.get("body", ""),
        )

    @classmethod
    def _get_username(cls, data: dict[str, t.Any]) -> str:
        user = data.get("user", {})
        if user is None:
            return "<ghost>"
        return user.get("login", "<ghost>")  # type: ignore[no-any-return]


# the first comment (as in a PR or Issue)
@dataclasses.dataclass(frozen=True, slots=True)
class ThreadStartComment(Comment):
    num_comments: int
    comments_url: str

    @classmethod
    def from_json(cls, data: dict[str, t.Any]) -> t.Self:
        return cls(
            user=cls._get_username(data),
            created_at=data.get("created_at"),
            body=data.get("body", ""),
            num_comments=data.get("comments", 0),
            comments_url=data["comments_url"],
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    notification: GHNotification
    status: str
    url: str

    @property
    def is_security_alert(self) -> bool:
        return self.notification.is_security_alert

    def matches_filter(self, filter: Filter, repo: str | None) -> bool:
        return (
            (Filter.MERGED not in filter or self.status == "merged")
            and (Filter.SECURITY not in filter or self.is_security_alert)
            and (Filter.REPO not in filter or self.notification.repo == repo)
        )
