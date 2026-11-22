import argparse
import asyncio

from .app import Dismisstress
from .data_models import CliArgs
from .gh_client import GithubClient


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
    owners = {o.strip().lower() for x in args.owners for o in x.split(",")}
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
