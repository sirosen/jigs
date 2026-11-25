from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from .data_models import (
    GHComment,
    GHCommentThread,
    GHReview,
    GHReviewThread,
)

_REVIEW_STYLES = {
    "APPROVED": "bold green",
    "CHANGES_REQUESTED": "bold red",
    "DISMISSED": "bold yellow",
}


def format_review_list(reviews: list[GHReview]) -> RenderableType | None:
    parts: list[RenderableType] = []
    for r in reviews:
        if r.is_empty:
            continue
        parts.extend(format_review(r))
    return Group(*parts) if parts else None


def format_review(review: GHReview) -> list[RenderableType]:
    parts: list[RenderableType] = [
        Text.assemble(
            ("── ", "bold"),
            (
                review.state.lower().replace("_", " "),
                _REVIEW_STYLES.get(review.state, "bold"),
            ),
            (f" · {review.user} · {review.submitted_at}", "bold"),
        )
    ]
    if review.body:
        parts.append(Padding(Text(review.body), (0, 0, 1, 2)))
    for thread in review.threads:
        parts.append(Padding(format_review_thread(thread), (0, 0, 1, 2)))
    return parts


def format_review_thread(thread: GHReviewThread) -> Panel:
    parts: list[RenderableType] = []
    for c in thread.comments:
        parts.append(Text(f"{c.user} · {c.created_at}", "bold"))
        parts.append(Padding(Text(c.body), (0, 0, 0, 2)))
    return Panel(
        Group(*parts),
        title=f"{thread.path}:{thread.line or '?'}",
        title_align="left",
        border_style="dim",
    )


def format_comment_thread(thread: GHCommentThread) -> RenderableType:
    parts = format_comment(thread.opening)
    if thread.num_hidden > 0:
        parts.append(
            Text(f"...{thread.num_hidden} older comments not shown...\n", "dim")
        )
    for comment in thread.comments:
        parts.extend(format_comment(comment))
    return Group(*parts)


def format_comment(post: GHComment) -> list[RenderableType]:
    return [
        Text(f"── {post.user} · {post.created_at}", "bold"),
        Padding(Text(post.body), (0, 0, 1, 2)),
    ]
