"""Phase 12 TDD tests — memory cleanup + intimacy decay + relationship archiving."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def _make_fragment(fid, ftype="short", importance=0.5, created_days_ago=0, retrievals=0):
    created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    return {
        "id": fid,
        "type": ftype,
        "importance": importance,
        "content": f"memory content {fid[:8]}",
        "created_at": created.isoformat(),
        "retrieval_count": retrievals,
    }


def _make_mock_agent(name="测试Agent"):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.nickname = name
    agent.solidified_memories = []
    return agent


# ── Phase 12a: Memory cleanup — expired fragments ──

def test_cleanup_low_importance_expired():
    """Short fragments with importance < 0.3 expire after short_retention_days_low (3d)."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("low-1", ftype="short", importance=0.1, created_days_ago=10),
        _make_fragment("low-2", ftype="short", importance=0.1, created_days_ago=1),
        _make_fragment("high-1", ftype="short", importance=0.8, created_days_ago=10),
    ]

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)

    remaining_ids = [f["id"] for f in agent.solidified_memories]
    assert "low-1" in removed, f"Expected low-1 expired, got removed={removed}"
    assert "low-2" in remaining_ids, "low-2 created 1 day ago should be kept"
    assert "high-1" in remaining_ids, "high-1 (importance >= 0.7) should be kept"


def test_cleanup_mid_importance_expired():
    """Short fragments with importance 0.3-0.7 expire after short_retention_days_mid (14d)."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("mid-1", ftype="short", importance=0.5, created_days_ago=30),
        _make_fragment("mid-2", ftype="short", importance=0.5, created_days_ago=5),
    ]

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)

    assert "mid-1" in removed, f"mid-1 30d old should expire, got removed={removed}"
    remaining_ids = [f["id"] for f in agent.solidified_memories]
    assert "mid-2" in remaining_ids, "mid-2 5d old should be kept"


def test_cleanup_high_importance_kept():
    """Short fragments with importance >= 0.7 are NOT expired by time."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("high-1", ftype="short", importance=0.9, created_days_ago=365),
        _make_fragment("high-2", ftype="short", importance=0.7, created_days_ago=100),
    ]

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)

    assert removed == [], f"High importance fragments should not expire, got {removed}"
    assert len(agent.solidified_memories) == 2


def test_cleanup_long_fragment_expired():
    """Long fragments expire after long_retention_days (90d)."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("long-1", ftype="long", importance=0.5, created_days_ago=120),
        _make_fragment("long-2", ftype="long", importance=0.5, created_days_ago=30),
    ]

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)

    assert "long-1" in removed, f"long-1 120d old should expire, got removed={removed}"
    remaining_ids = [f["id"] for f in agent.solidified_memories]
    assert "long-2" in remaining_ids, "long-2 30d old should be kept"


def test_cleanup_core_never_expires():
    """Core fragments are never cleaned up by time."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("core-1", ftype="core", importance=0.9, created_days_ago=1000),
    ]

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)

    assert removed == [], f"Core fragments should never expire, got {removed}"


def test_cleanup_no_fragments():
    """Empty or None fragments list returns empty removed list."""
    agent = _make_mock_agent()
    agent.solidified_memories = None

    from app.engine.memory_engine import cleanup_agent_memories
    removed = cleanup_agent_memories(agent)
    assert removed == []

    agent.solidified_memories = []
    removed = cleanup_agent_memories(agent)
    assert removed == []


# ── Phase 12b: Memory cleanup — capacity eviction ──

def test_evict_short_over_capacity():
    """When short fragments exceed max_short_fragments, evict lowest importance*time_decay."""
    agent = _make_mock_agent()
    # Create 155 short fragments (max is 150)
    fragments = []
    for i in range(155):
        importance = 0.1 + (i % 10) * 0.05  # varying importance
        fragments.append(_make_fragment(
            f"s{i:04d}", ftype="short", importance=importance,
            created_days_ago=10 + (i % 30),
        ))
    agent.solidified_memories = fragments

    from app.engine.memory_engine import evict_over_capacity
    removed = evict_over_capacity(agent)

    assert len(agent.solidified_memories) <= 150, (
        f"Expected <= 150 short fragments, got {len(agent.solidified_memories)}"
    )
    # Should have removed at least 5
    assert len(removed) >= 5, f"Expected >= 5 evictions, got {len(removed)}"


def test_evict_long_over_capacity():
    """When long fragments exceed max_long_fragments, evict lowest importance*time_decay."""
    agent = _make_mock_agent()
    # Create 55 long fragments (max is 50)
    fragments = []
    for i in range(55):
        fragments.append(_make_fragment(
            f"l{i:04d}", ftype="long", importance=0.3 + (i % 10) * 0.02,
            created_days_ago=50 + (i % 40),
        ))
    agent.solidified_memories = fragments

    from app.engine.memory_engine import evict_over_capacity
    removed = evict_over_capacity(agent)

    assert len(agent.solidified_memories) <= 50, (
        f"Expected <= 50 long fragments, got {len(agent.solidified_memories)}"
    )
    assert len(removed) >= 5, f"Expected >= 5 evictions, got {len(removed)}"


def test_evict_under_capacity_noop():
    """No eviction when under capacity."""
    agent = _make_mock_agent()
    agent.solidified_memories = [
        _make_fragment("s001", ftype="short", importance=0.5, created_days_ago=5),
        _make_fragment("l001", ftype="long", importance=0.6, created_days_ago=10),
    ]

    from app.engine.memory_engine import evict_over_capacity
    removed = evict_over_capacity(agent)

    assert removed == [], f"Under capacity should not evict, got {removed}"
    assert len(agent.solidified_memories) == 2


# ── Phase 12c: Intimacy decay ──

def test_decay_intimacy_stale():
    """Intimacy decays for relationships with last_interaction > 7 days."""
    from unittest.mock import AsyncMock, MagicMock
    from datetime import timezone

    async def _run():
        from app.engine.memory_engine import decay_all_intimacy

        now = datetime.now(timezone.utc)
        mock_db = AsyncMock()

        # Stale relationship: last interaction 20 days ago
        rel_stale = MagicMock()
        rel_stale.id = uuid.uuid4()
        rel_stale.intimacy = 0.5
        rel_stale.last_interaction = now - timedelta(days=20)
        rel_stale.is_archived = False

        # Recent relationship: last interaction 1 day ago
        rel_recent = MagicMock()
        rel_recent.id = uuid.uuid4()
        rel_recent.intimacy = 0.3
        rel_recent.last_interaction = now - timedelta(days=1)
        rel_recent.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel_stale, rel_recent]
        mock_db.execute = AsyncMock(return_value=mock_result)

        decayed_count = await decay_all_intimacy(mock_db)

        # Stale should decay: 20 - 7 = 13 days * 0.01 = 0.13
        expected = 0.5 - 0.13
        assert abs(rel_stale.intimacy - expected) < 0.02, (
            f"Expected intimacy ~{expected}, got {rel_stale.intimacy}"
        )
        # Recent should not decay
        assert rel_recent.intimacy == 0.3, (
            f"Recent should not decay, got {rel_recent.intimacy}"
        )
        assert mock_db.commit.called
        assert decayed_count == 1

    asyncio.run(_run())


def test_no_decay_recent_interaction():
    """No intimacy decay when last_interaction <= 7 days."""
    async def _run():
        from app.engine.memory_engine import decay_all_intimacy

        now = datetime.now(timezone.utc)
        mock_db = AsyncMock()

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.intimacy = 0.8
        rel.last_interaction = now - timedelta(days=3)
        rel.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel]
        mock_db.execute = AsyncMock(return_value=mock_result)

        decayed_count = await decay_all_intimacy(mock_db)

        assert rel.intimacy == 0.8, f"Recent interaction should not decay"
        assert decayed_count == 0

    asyncio.run(_run())


def test_decay_respects_floor():
    """Intimacy does not drop below -1.0."""
    async def _run():
        from app.engine.memory_engine import decay_all_intimacy

        now = datetime.now(timezone.utc)
        mock_db = AsyncMock()

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.intimacy = -0.95
        rel.last_interaction = now - timedelta(days=100)
        rel.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel]
        mock_db.execute = AsyncMock(return_value=mock_result)

        await decay_all_intimacy(mock_db)

        assert rel.intimacy >= -1.0, f"Intimacy should not go below -1.0, got {rel.intimacy}"

    asyncio.run(_run())


def test_decay_no_last_interaction():
    """If last_interaction is None, skip decay."""
    async def _run():
        from app.engine.memory_engine import decay_all_intimacy

        mock_db = AsyncMock()

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.intimacy = 0.5
        rel.last_interaction = None
        rel.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel]
        mock_db.execute = AsyncMock(return_value=mock_result)

        decayed_count = await decay_all_intimacy(mock_db)

        assert rel.intimacy == 0.5, "No last_interaction should skip decay"
        assert decayed_count == 0

    asyncio.run(_run())


# ── Phase 12d: Relationship archiving ──

def test_archive_cold_relationship():
    """Archive relationships with intimacy < 0.1 and last_interaction > 30 days."""
    async def _run():
        from app.engine.memory_engine import archive_cold_relationships

        now = datetime.now(timezone.utc)
        mock_db = AsyncMock()

        rel_cold = MagicMock()
        rel_cold.id = uuid.uuid4()
        rel_cold.intimacy = 0.05
        rel_cold.last_interaction = now - timedelta(days=60)
        rel_cold.is_archived = False

        rel_active = MagicMock()
        rel_active.id = uuid.uuid4()
        rel_active.intimacy = 0.5
        rel_active.last_interaction = now - timedelta(days=60)
        rel_active.is_archived = False

        rel_recent = MagicMock()
        rel_recent.id = uuid.uuid4()
        rel_recent.intimacy = 0.05
        rel_recent.last_interaction = now - timedelta(days=10)
        rel_recent.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel_cold, rel_active, rel_recent]
        mock_db.execute = AsyncMock(return_value=mock_result)

        archived_count = await archive_cold_relationships(mock_db)

        assert rel_cold.is_archived is True, "Cold relationship should be archived"
        assert rel_active.is_archived is False, "Active intimacy should not archive"
        assert rel_recent.is_archived is False, "Recent interaction should not archive"
        assert mock_db.commit.called
        assert archived_count == 1

    asyncio.run(_run())


def test_archive_none_last_interaction():
    """If last_interaction is None, skip archiving."""
    async def _run():
        from app.engine.memory_engine import archive_cold_relationships

        mock_db = AsyncMock()

        rel = MagicMock()
        rel.id = uuid.uuid4()
        rel.intimacy = 0.05
        rel.last_interaction = None
        rel.is_archived = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [rel]
        mock_db.execute = AsyncMock(return_value=mock_result)

        archived_count = await archive_cold_relationships(mock_db)

        assert rel.is_archived is False, "No last_interaction should skip archive"
        assert archived_count == 0

    asyncio.run(_run())


# ── Phase 12e: DailyTask registration ──

def test_memory_cleanup_task_registered():
    """memory_cleanup and intimacy_maintenance are registered as DailyTasks."""
    import app.jobs.scheduler  # triggers module-level DailyTask registration
    from app.engine.daily_tasks import daily_task_registry

    names = [name for name, _, _, _ in daily_task_registry._tasks]
    assert "memory_cleanup" in names, (
        f"memory_cleanup not in registered tasks: {names}"
    )
    assert "intimacy_maintenance" in names, (
        f"intimacy_maintenance not in registered tasks: {names}"
    )


# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    tests = [
        (name, obj) for name, obj in list(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    if failed:
        import sys
        sys.exit(1)
