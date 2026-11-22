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
class GHSubject:
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
    repo: str  # owner/name
    subject: GHSubject

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
            repo=data["repository"]["full_name"],
            subject=GHSubject(s["title"], s["type"], s["url"], s["latest_comment_url"]),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    notification: GHNotification
    status: str
    url: str

    @property
    def is_security_alert(self) -> bool:
        return self.notification.is_security_alert
