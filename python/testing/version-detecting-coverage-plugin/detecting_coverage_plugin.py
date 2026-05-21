from __future__ import annotations

import operator
import typing as t

from coverage import CoveragePlugin
from coverage.config import CoverageConfig
from coverage.plugin_support import Plugins


PACKAGE_NAME = "my-very-cool-lib"

MIN_SUPPORTED_V1_RELEASE = (1, 22)
MAX_SUPPORTED_V1_RELEASE = (1, 26)

MIN_SUPPORTED_V2_RELEASE = (2, 0)
MAX_SUPPORTED_V2_RELEASE = (2, 12)

COMPARATORS: list[tuple[str, t.Callable[[tuple[int, int], tuple[int, int]], bool]]] = [
    ("<", operator.lt),
    ("<=", operator.le),
    (">", operator.gt),
    (">=", operator.ge),
    ("==", operator.eq),
]


def get_current_major_minor() -> tuple[int, int]:
    # pretend this calls importlib metadata
    return (1, 3)


def iter_all_supported_versions() -> t.Iterator[tuple[int, int]]:
    v1_min_minor = MIN_SUPPORTED_V1_RELEASE[1]
    v1_max_minor = MAX_SUPPORTED_V1_RELEASE[1]
    for minor in range(v1_min_minor, v1_max_minor + 1):
        yield (1, minor)
    v2_min_minor = MIN_SUPPORTED_V2_RELEASE[1]
    v2_max_minor = MAX_SUPPORTED_V2_RELEASE[1]
    for minor in range(v2_min_minor, v2_max_minor + 1):
        yield (2, minor)


def iter_version_exclude_pragmas() -> t.Iterator[str]:
    current_major, current_minor = get_current_major_minor()

    yield rf"# pragma: {PACKAGE_NAME}=={current_major}.{current_minor} no cover\b"

    for major, minor in iter_all_supported_versions():
        for opname, opfunc in COMPARATORS:
            comparator_applies = opfunc((current_major, current_minor), (major, minor))
            designator = "no cover" if comparator_applies else "cover"
            yield rf"# pragma: {PACKAGE_NAME}{opname}{major}.{minor} {designator}\b"


# mypy flags CoveragePlugin as being of type Any, type ignore "subclassing Any"
class PipVersionPragmas(CoveragePlugin):  # type: ignore[misc]
    def configure(self, config: CoverageConfig) -> None:
        exclude_lines = (
            set(config.get_option("report:exclude_lines"))
            | set(iter_version_exclude_pragmas())
        )
        config.set_option("report:exclude_lines", sorted(exclude_lines))


def coverage_init(registry: Plugins, options: dict[str, object]) -> None:
    registry.add_configurer(PipVersionPragmas())


if __name__ == "__main__":
    # as a simple runnable demo, print all of the computed pragmas
    for pragma in iter_version_exclude_pragmas():
        print(pragma)
