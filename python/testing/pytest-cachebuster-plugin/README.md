# cachebuster

This is a simple cache busting plugin for pytest.
You can stuff it into a conftest.py or put it in a place where you point pytest_plugins.

The idea is to find and clear all functools LRU caches in a package whenever
test teardown happens.
