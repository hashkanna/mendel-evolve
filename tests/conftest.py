import os

import pytest

from toyhelpers import TOY_PROBLEM


@pytest.fixture(autouse=True, scope="session")
def build_cache(tmp_path_factory):
    """Keep test builds out of ~/.cache. Set before any worker process starts, so they inherit it."""
    path = tmp_path_factory.mktemp("builds")
    os.environ["MENDEL_BUILD_CACHE"] = str(path)
    return path


@pytest.fixture(scope="session")
def pool(build_cache):
    """A small shared process pool; other jobs are using this machine."""
    from mendel.executor import LocalExecutor

    ex = LocalExecutor(workers=3)
    yield ex
    ex.close()


@pytest.fixture(scope="session")
def problem():
    from mendel.problem import load_problem

    return load_problem(TOY_PROBLEM)
