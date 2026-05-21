import inspect
import pkgutil
import sys
import types
import typing as t

import pytest


class CacheBuster:
    """
    A CacheBuster is a module/package search tool which traverses a package, finds all
    global caches in that package, and offers a one-shot `clear_caches` method.
    """

    def __init__(
        self,
        base_package_name: str,
        *,
        exclude_module_names: t.Iterable[str] = (),
        exclude_types: t.Iterable[type] = (),
    ) -> None:
        self._base_package_name = base_package_name
        self._exclude_module_names = frozenset(exclude_module_names)
        self._exclude_types = tuple(exclude_types)
        self._caches: list[tuple[str, t.Any]] = []
        self._scanned_modules: set[str] = set()

    def register_cache(self, name: str, cache: t.Any) -> None:
        """
        Explicitly register a cache. This method can be used when default discovery
        is unable to detect a cache -- e.g., because it is lazily initialized.
        """
        self._caches.append((name, cache))

    def clear_caches(self, *, namespace: str | None = None) -> None:
        self._discover_caches()
        for name, cache in self._caches:
            if namespace is not None and not name.startswith(f"{namespace}."):
                continue
            cache.cache_clear()

    def _discover_caches(self) -> None:
        for modname, mod in self._scan_modules():
            self._scanned_modules.add(modname)

            for name, obj in inspect.getmembers(mod):
                if isinstance(obj, self._exclude_types):
                    continue
                if _looks_like_cached_func(obj):
                    # skip things where the `__module__` does not match
                    # these cases are presumed to be imports of a cached function
                    if obj.__module__ != modname:
                        continue
                    self.register_cache(f"{modname}.{name}", obj)

    def _scan_modules(self) -> t.Iterator[tuple[str, types.ModuleType]]:
        pkg_path = __import__(self._base_package_name).__path__
        for _, name, _ in pkgutil.walk_packages(
            path=pkg_path, prefix=f"{self._base_package_name}."
        ):
            if name in self._exclude_module_names:
                continue
            if name in self._scanned_modules:
                continue
            if name in sys.modules:
                yield name, sys.modules[name]


# a separate "runner" object as a concept provides finer grained control over the
# time and subpackage over which a cache buster runs
class CacheBusterRunner:
    def __init__(self, cache_buster: CacheBuster, target_namespace: str) -> None:
        self._cache_buster = cache_buster
        self._target_namespace = target_namespace

        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def __call__(self) -> None:
        if not self._enabled:
            return

        self._cache_buster.clear_caches(namespace=self._target_namespace)


# it's not clear how we can find caches -- as a very simple heuristic, does it bear the
# external signature of a functools LRU cache?
def _looks_like_cached_func(obj: object) -> bool:
    if not callable(obj):
        return False
    if not hasattr(obj, "cache_info"):
        return False
    if cache_clear := getattr(obj, "cache_clear", None):
        return callable(cache_clear)
    return False


# there is a single session-global cache buster, since generally incremental discovery
# of caches will not need to re-run
# this also serves as a good place to define the types or other exclude rules for your
# package
@pytest.fixture(scope="session")
def cache_buster() -> CacheBuster:
    # werkzeug is used to pass LocalProxy to exclude_types -- this is a great example of
    # why 'exclude_types' exists, as trying to poke at a LocalProxy will cause errors if
    # you don't control the context in which it happens
    import werkzeug

    return CacheBuster("my_package", exclude_types=(werkzeug.local.LocalProxy,))


@pytest.fixture(autouse=True)
def automatically_run_cache_buster_on_teardown(cache_buster) -> CacheBusterRunner:
    runner = CacheBusterRunner(cache_buster, "my_package")

    yield runner

    runner()
