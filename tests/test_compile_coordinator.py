import asyncio

import pytest

from app.compile_coordinator import CompileCoordinator


@pytest.mark.asyncio
async def test_coalesces_same_key():
    coordinator = CompileCoordinator()
    call_counter = {"count": 0}

    async def create_task():
        call_counter["count"] += 1
        await asyncio.sleep(0.01)
        return {"success": True}

    first = asyncio.create_task(coordinator.run("project-1", "key-a", create_task))
    second = asyncio.create_task(coordinator.run("project-1", "key-a", create_task))
    result_one, _ = await first
    result_two, _ = await second

    assert result_one["success"] is True
    assert result_two["success"] is True
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_cancels_old_task_for_new_key():
    coordinator = CompileCoordinator()
    cancelled_event = asyncio.Event()

    async def slow_task():
        try:
            await asyncio.sleep(0.3)
            return {"success": True}
        except asyncio.CancelledError:
            cancelled_event.set()
            raise

    async def fast_task():
        await asyncio.sleep(0.01)
        return {"success": True}

    old_request = asyncio.create_task(coordinator.run("project-1", "old-key", slow_task))
    await asyncio.sleep(0.05)
    new_request = asyncio.create_task(coordinator.run("project-1", "new-key", fast_task))

    with pytest.raises(asyncio.CancelledError):
        await old_request

    new_result, _ = await new_request
    assert new_result["success"] is True
    assert cancelled_event.is_set()
