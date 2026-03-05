import pytest

from app.workdir_cache import WorkdirCache


@pytest.mark.asyncio
async def test_workdir_reused_per_project(tmp_path):
    cache = WorkdirCache(root_dir=str(tmp_path), max_projects=10)
    workdir_one = await cache.acquire("project-1")
    await cache.release("project-1")

    workdir_two = await cache.acquire("project-1")
    await cache.release("project-1")

    assert workdir_one == workdir_two
    assert workdir_one.exists()


@pytest.mark.asyncio
async def test_workdir_lru_evicts_released_entries(tmp_path):
    cache = WorkdirCache(root_dir=str(tmp_path), max_projects=1)

    dir_one = await cache.acquire("project-1")
    await cache.release("project-1")

    await cache.acquire("project-2")
    await cache.release("project-2")

    assert not dir_one.exists()


@pytest.mark.asyncio
async def test_workdir_does_not_evict_in_use_entries(tmp_path):
    cache = WorkdirCache(root_dir=str(tmp_path), max_projects=1)
    dir_one = await cache.acquire("project-1")
    await cache.acquire("project-2")
    await cache.release("project-2")

    assert dir_one.exists()
    await cache.release("project-1")
