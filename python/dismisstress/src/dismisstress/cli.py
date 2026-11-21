import argparse

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
    args = parse_args()
    client = GithubClient()
    Dismisstress(args, client).run()


if __name__ == "__main__":
    main()
