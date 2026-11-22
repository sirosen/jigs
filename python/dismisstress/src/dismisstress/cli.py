import argparse
import asyncio
import typing as t

from .app import Dismisstress
from .data_models import CliArgs
from .gh_client import GithubClient


def _split_owners(owners: list[str]) -> t.Iterator[str]:
    for value in owners:
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            yield item.lower()


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
    owners = set(_split_owners(args.owners))
    return CliArgs(owners=tuple(owners) if owners else None)


def main() -> None:
    asyncio.run(_app())


async def _app() -> None:
    args = parse_args()
    client = GithubClient()
    try:
        await Dismisstress(args, client).run_async()
    finally:
        await client.close()


if __name__ == "__main__":
    main()
