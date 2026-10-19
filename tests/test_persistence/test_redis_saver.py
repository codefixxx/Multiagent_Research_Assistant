"""Unit tests for Redis checkpointer, run manager, and idempotency cache."""

import pytest

from src.persistence.redis_saver import (
    NodeIdempotencyCache,
    RedisRunManager,
    get_checkpointer,
    get_redis_client,
)


@pytest.mark.asyncio
async def test_get_redis_client_fake_fallback():
    client = await get_redis_client(force_fake=True)
    assert client is not None
    await client.set("test_key", "test_value")
    val = await client.get("test_key")
    val_str = val.decode("utf-8") if isinstance(val, bytes) else val
    assert val_str == "test_value"


@pytest.mark.asyncio
async def test_get_checkpointer():
    checkpointer = await get_checkpointer(force_fake=True)
    assert checkpointer is not None
    # Check that checkpointer has async checkpoint methods
    assert hasattr(checkpointer, "aput")
    assert hasattr(checkpointer, "aget_tuple")


@pytest.mark.asyncio
async def test_redis_run_manager():
    client = await get_redis_client(force_fake=True)
    manager = RedisRunManager(redis_client=client)

    run_id = "test-run-101"
    query = "Distributed database consensus protocols"

    # 1. Initialize run
    init_meta = await manager.init_run(run_id, query)
    assert init_meta["run_id"] == run_id
    assert init_meta["query"] == query
    assert init_meta["status"] == "planning"

    # 2. Get metadata
    fetched_meta = await manager.get_run_metadata(run_id)
    assert fetched_meta is not None
    assert fetched_meta["status"] == "planning"

    # 3. Update status
    updated_meta = await manager.update_run_status(
        run_id=run_id,
        status="researching",
        current_node="researcher",
        step_count=2,
        total_tokens=1500,
    )
    assert updated_meta is not None
    assert updated_meta["status"] == "researching"
    assert updated_meta["current_node"] == "researcher"
    assert updated_meta["step_count"] == 2
    assert updated_meta["total_tokens"] == 1500

    # 4. Record and get steps
    await manager.record_completed_step(run_id, "planner", 1)
    await manager.record_completed_step(run_id, "researcher", 2)
    history = await manager.get_step_history(run_id)
    assert len(history) == 2
    assert history[0]["node"] == "planner"
    assert history[1]["node"] == "researcher"

    # 5. Clear run
    await manager.clear_run(run_id)
    assert await manager.get_run_metadata(run_id) is None
    assert await manager.get_step_history(run_id) == []


@pytest.mark.asyncio
async def test_node_idempotency_cache():
    client = await get_redis_client(force_fake=True)
    cache = NodeIdempotencyCache(redis_client=client)

    run_id = "test-run-202"
    node_name = "researcher"
    payload = {"sub_question_id": "sq-1", "query": "Raft vs Paxos"}
    output = {
        "findings": [
            {"claim": "Raft decomposes consensus into leader election and log replication."}
        ]
    }

    # Initial miss
    miss = await cache.get(run_id, node_name, payload)
    assert miss is None

    # Cache hit after set
    await cache.set(run_id, node_name, payload, output)
    hit = await cache.get(run_id, node_name, payload)
    assert hit is not None
    assert (
        hit["findings"][0]["claim"]
        == "Raft decomposes consensus into leader election and log replication."
    )


@pytest.mark.asyncio
async def test_redis_run_manager_auto_expire_ttl():
    """Verify ephemeral scratchpad TTL policy auto-expires all run artifacts."""
    client = await get_redis_client(force_fake=True)
    ttl_seconds = 3600
    manager = RedisRunManager(redis_client=client, default_ttl_seconds=ttl_seconds)

    run_id = "test-ttl-run-303"
    query = "Ephemeral storage lifecycle verification"

    # 1. Metadata TTL on init
    await manager.init_run(run_id, query)
    meta_ttl = await client.ttl(manager._meta_key(run_id))
    assert 0 < meta_ttl <= ttl_seconds

    # 2. Steps list TTL
    await manager.record_completed_step(run_id, "planner", 1)
    steps_ttl = await client.ttl(manager._steps_key(run_id))
    assert 0 < steps_ttl <= ttl_seconds

    # 3. Report TTL
    sample_report = {"title": "TTL Report", "sections": []}
    await manager.save_report(run_id, sample_report)
    report_ttl = await client.ttl(manager._report_key(run_id))
    assert 0 < report_ttl <= ttl_seconds

    # 4. Audit trace TTL
    sample_trace = {"run_id": run_id, "status": "completed"}
    await manager.save_audit_log(run_id, sample_trace)
    trace_ttl = await client.ttl(manager._trace_key(run_id))
    assert 0 < trace_ttl <= ttl_seconds

    # 5. Metadata TTL preserved on status update
    await manager.update_run_status(run_id, status="completed", current_node="done")
    updated_meta_ttl = await client.ttl(manager._meta_key(run_id))
    assert 0 < updated_meta_ttl <= ttl_seconds

    # 6. Apply TTL refreshes all keys uniformly
    new_ttl = 7200
    await manager.apply_ttl(run_id, ttl_seconds=new_ttl)
    refreshed_meta_ttl = await client.ttl(manager._meta_key(run_id))
    refreshed_report_ttl = await client.ttl(manager._report_key(run_id))
    assert 3600 < refreshed_meta_ttl <= new_ttl
    assert 3600 < refreshed_report_ttl <= new_ttl


@pytest.mark.asyncio
async def test_redis_run_manager_disabled_ttl():
    """Verify TTL is disabled when default_ttl_seconds=0 (permanent storage mode)."""
    client = await get_redis_client(force_fake=True)
    manager = RedisRunManager(redis_client=client, default_ttl_seconds=0)

    run_id = "test-permanent-run-404"
    await manager.init_run(run_id, "Permanent retention test")
    meta_ttl = await client.ttl(manager._meta_key(run_id))
    # In Redis/FakeRedis, TTL is -1 when key exists with no expiration
    assert meta_ttl == -1

    await manager.save_report(run_id, {"title": "Permanent"})
    report_ttl = await client.ttl(manager._report_key(run_id))
    assert report_ttl == -1
