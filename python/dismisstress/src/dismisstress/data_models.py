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


@dataclasses.dataclass(frozen=True, slots=True)
class GHComment:
    user: str
    created_at: str | None
    body: str

    @classmethod
    def from_json(cls, data: dict[str, t.Any]) -> GHComment:
        return cls(_login(data), data.get("created_at"), data.get("body") or "")


@dataclasses.dataclass(frozen=True, slots=True)
class GHCommentThread:
    opening: GHComment
    # comments may be truncated for long threads
    comments: tuple[GHComment, ...]
    total: int

    @property
    def num_hidden(self) -> int:
        return self.total - len(self.comments)

    @classmethod
    def from_json(
        cls, issue: dict[str, t.Any], comments: list[dict[str, t.Any]]
    ) -> GHCommentThread:
        return cls(
            opening=GHComment.from_json(issue),
            comments=tuple(GHComment.from_json(c) for c in comments),
            total=issue.get("comments", 0),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class GHReviewComment:  # a comment on a line in a PR file
    id: int
    review_id: int | None
    in_reply_to_id: int | None
    path: str
    line: int | None
    comment: GHComment

    @property
    def thread_key(self) -> int:
        if self.in_reply_to_id is not None:
            return self.in_reply_to_id
        return self.id

    @classmethod
    def from_json(cls, data: dict[str, t.Any]) -> GHReviewComment:
        return cls(
            id=data["id"],
            review_id=data.get("pull_request_review_id"),
            in_reply_to_id=data.get("in_reply_to_id"),
            path=data["path"],
            line=data.get("line") or data.get("original_line"),
            comment=GHComment.from_json(data),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class GHReviewThread:  # a review comment plus its replies
    path: str
    line: int | None
    comments: tuple[GHComment, ...]

    @classmethod
    def from_review_comments(cls, chain: list[GHReviewComment]) -> GHReviewThread:
        return cls(chain[0].path, chain[0].line, tuple(c.comment for c in chain))


@dataclasses.dataclass(frozen=True, slots=True)
class GHReview:
    state: str
    user: str
    submitted_at: str | None
    body: str
    threads: tuple[GHReviewThread, ...]  # the threads this review started

    @property
    def is_empty(self) -> bool:
        # a review which replies to prior reviews but doesn't have a top-level body
        # and doesn't start new threads is "empty"
        return self.state == "COMMENTED" and not self.body and not self.threads

    @classmethod
    def from_json(
        cls, data: dict[str, t.Any], threads: tuple[GHReviewThread, ...]
    ) -> GHReview:
        return cls(
            state=data["state"],
            user=_login(data),
            submitted_at=data.get("submitted_at"),
            body=data.get("body") or "",
            threads=threads,
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


def _login(data: dict[str, t.Any]) -> str:
    user = data.get("user") or data.get("author") or {}
    return str(user.get("login", "<ghost>"))
