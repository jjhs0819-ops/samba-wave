import asyncio

import pytest

from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
from backend.shutdown_state import clear_shutting_down, mark_shutting_down


@pytest.fixture(autouse=True)
def reset_shutdown_queue_state():
    clear_shutting_down()
    SourcingQueue.queue.clear()
    SourcingQueue.resolvers.clear()
    yield
    clear_shutting_down()
    SourcingQueue.queue.clear()
    SourcingQueue.resolvers.clear()


def test_sourcing_queue_add_and_resolve_job():
    async def scenario():
        request_id, future = SourcingQueue.add_search_job("ABCmart", "nike")

        job = SourcingQueue.get_next_job()
        assert job["hasJob"] is True
        assert job["requestId"] == request_id
        assert job["site"] == "ABCmart"
        assert job["keyword"] == "nike"

        assert (
            SourcingQueue.resolve_job(
                request_id,
                {"success": True, "products": []},
            )
            is True
        )
        assert await future == {"success": True, "products": []}

    asyncio.run(scenario())


def test_sourcing_queue_rejects_new_jobs_while_shutting_down():
    mark_shutting_down()

    with pytest.raises(RuntimeError, match="server is shutting down"):
        SourcingQueue.add_search_job("ABCmart", "nike")

    assert SourcingQueue.get_next_job() == {"hasJob": False, "shuttingDown": True}


def test_sourcing_queue_cancel_all_fails_waiters():
    async def scenario():
        _, future = SourcingQueue.add_detail_job("ABCmart", "12345")

        SourcingQueue.cancel_all("shutdown for deploy")

        with pytest.raises(RuntimeError, match="shutdown for deploy"):
            await future

        assert SourcingQueue.queue == []
        assert SourcingQueue.resolvers == {}

    asyncio.run(scenario())
