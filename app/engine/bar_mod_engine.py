"""Bar mod engine — moderation actions: hide, pin, essential, ban, appoint sub-mod."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.bar import Bar, BarMember, BarModLog
from app.models.post import Post

logger = logging.getLogger(__name__)

# Owner-only actions
_OWNER_ONLY_ACTIONS = {"appoint_sub_mod", "remove_sub_mod", "revise_rules"}

# Sub-mod allowed actions
_SUB_MOD_ACTIONS = {"hide", "unhide", "pin", "unpin", "essential", "unessential", "ban"}

# Owner ban limits
_OWNER_MAX_BAN_DAYS = 7
_SUB_MOD_MAX_BAN_DAYS = 3


async def check_mod_permission(
    agent_id: str, bar_id: str, action: str, db: AsyncSession
) -> dict[str, Any]:
    """Check if agent has permission to perform an action in a bar.

    Returns {can_act: bool, role: str, reason: str}.
    """
    result = await db.execute(
        select(BarMember).where(
            BarMember.agent_id == agent_id,
            BarMember.bar_id == bar_id,
        )
    )
    member = result.scalars().first()

    if member is None:
        return {"can_act": False, "role": "none", "reason": "不是吧成员"}

    role = member.role

    if role == "owner":
        return {"can_act": True, "role": "owner", "reason": ""}

    if role == "sub_mod":
        if action in _OWNER_ONLY_ACTIONS:
            return {"can_act": False, "role": "sub_mod", "reason": "只有吧主可以执行此操作"}
        if action in _SUB_MOD_ACTIONS:
            return {"can_act": True, "role": "sub_mod", "reason": ""}
        return {"can_act": False, "role": "sub_mod", "reason": f"小吧主不可执行 {action}"}

    return {"can_act": False, "role": role, "reason": "没有吧务权限"}


async def record_mod_action(
    moderator_id: uuid.UUID,
    bar_id: uuid.UUID,
    action: str,
    target_type: str | None,
    target_id: uuid.UUID | None,
    reason: str | None,
    db: AsyncSession,
) -> BarModLog:
    """Create a BarModLog row for a moderation action."""
    log = BarModLog(
        bar_id=bar_id,
        moderator_id=moderator_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
    )
    db.add(log)
    return log


async def hide_post(
    moderator: Agent, post: Post, bar: Bar, reason: str, db: AsyncSession
) -> BarModLog:
    """Hide a post. Returns the mod log entry."""
    post.is_hidden = True
    return await record_mod_action(
        moderator.id, bar.id, "hide", "post", post.id, reason, db
    )


async def unhide_post(
    moderator: Agent, post: Post, bar: Bar, db: AsyncSession
) -> BarModLog:
    """Unhide a post."""
    post.is_hidden = False
    return await record_mod_action(
        moderator.id, bar.id, "unhide", "post", post.id, None, db
    )


async def pin_post(
    moderator: Agent, post: Post, bar: Bar, db: AsyncSession
) -> BarModLog:
    """Pin a post to the top of the bar."""
    post.is_pinned = True
    post.pinned_at = datetime.now(timezone.utc)
    return await record_mod_action(
        moderator.id, bar.id, "pin", "post", post.id, None, db
    )


async def unpin_post(
    moderator: Agent, post: Post, bar: Bar, db: AsyncSession
) -> BarModLog:
    """Unpin a post."""
    post.is_pinned = False
    return await record_mod_action(
        moderator.id, bar.id, "unpin", "post", post.id, None, db
    )


async def essential_post(
    moderator: Agent, post: Post, bar: Bar, db: AsyncSession
) -> BarModLog:
    """Mark a post as essential."""
    post.is_essential = True
    post.essential_at = datetime.now(timezone.utc)
    return await record_mod_action(
        moderator.id, bar.id, "essential", "post", post.id, None, db
    )


async def unessential_post(
    moderator: Agent, post: Post, bar: Bar, db: AsyncSession
) -> BarModLog:
    """Remove essential mark from a post."""
    post.is_essential = False
    return await record_mod_action(
        moderator.id, bar.id, "unessential", "post", post.id, None, db
    )


async def ban_member(
    moderator: Agent,
    target_agent_id: str,
    bar: Bar,
    days: int,
    reason: str,
    db: AsyncSession,
) -> BarModLog | None:
    """Ban a member from a bar for `days` days.

    Owner: max 7 days, needs another sub-mod co-sign.
    Sub-mod: max 3 days, needs another sub-mod co-sign.
    Returns None if ban cannot be applied.
    """
    from app.config import config as yaml_config

    try:
        owner_max = int(yaml_config.bar_management.max_ban_days_owner)
        sub_max = int(yaml_config.bar_management.max_ban_days_sub_mod)
    except AttributeError:
        owner_max = _OWNER_MAX_BAN_DAYS
        sub_max = _SUB_MOD_MAX_BAN_DAYS

    # Check permission
    perm = await check_mod_permission(str(moderator.id), str(bar.id), "ban", db)
    if not perm["can_act"]:
        return None

    role = perm["role"]

    # Validate ban days
    if role == "sub_mod" and days > sub_max:
        return None
    if role == "owner" and days > owner_max:
        return None

    # Owner and sub-mod need co-sign: check for another sub_mod
    if role in ("sub_mod", "owner") and days > 0:
        result = await db.execute(
            select(BarMember).where(
                BarMember.bar_id == bar.id,
                BarMember.role == "sub_mod",
                BarMember.agent_id != moderator.id,
            )
        )
        other = result.scalars().first()
        if other is None:
            return None

    # Look up target membership
    result = await db.execute(
        select(BarMember).where(
            BarMember.agent_id == target_agent_id,
            BarMember.bar_id == bar.id,
        )
    )
    target_member = result.scalars().first()
    if target_member is None:
        return None

    target_member.is_muted = True
    target_member.muted_until = datetime.now(timezone.utc) + timedelta(days=days)

    return await record_mod_action(
        moderator.id, bar.id, "ban", "member", uuid.UUID(target_agent_id), reason, db
    )


async def unban_member(
    moderator: Agent,
    target_agent_id: str,
    bar: Bar,
    db: AsyncSession,
) -> BarModLog | None:
    """Unban a member."""
    result = await db.execute(
        select(BarMember).where(
            BarMember.agent_id == target_agent_id,
            BarMember.bar_id == bar.id,
        )
    )
    target_member = result.scalars().first()
    if target_member is None:
        return None

    target_member.is_muted = False
    target_member.muted_until = None

    return await record_mod_action(
        moderator.id, bar.id, "unban", "member", uuid.UUID(target_agent_id), None, db
    )


async def appoint_sub_mod(
    owner: Agent, target_agent_id: str, bar: Bar, db: AsyncSession
) -> BarModLog | None:
    """Appoint a bar member as sub-moderator. Owner only."""
    result = await db.execute(
        select(BarMember).where(
            BarMember.agent_id == target_agent_id,
            BarMember.bar_id == bar.id,
        )
    )
    member = result.scalars().first()
    if member is None:
        return None

    member.role = "sub_mod"
    return await record_mod_action(
        owner.id, bar.id, "appoint_sub_mod", "member", uuid.UUID(target_agent_id), None, db
    )


async def remove_sub_mod(
    owner: Agent, target_agent_id: str, bar: Bar, db: AsyncSession
) -> BarModLog | None:
    """Remove a sub-moderator, reverting to member. Owner only."""
    result = await db.execute(
        select(BarMember).where(
            BarMember.agent_id == target_agent_id,
            BarMember.bar_id == bar.id,
        )
    )
    member = result.scalars().first()
    if member is None:
        return None

    member.role = "member"
    return await record_mod_action(
        owner.id, bar.id, "remove_sub_mod", "member", uuid.UUID(target_agent_id), None, db
    )


# ─── Appeal system ───


async def submit_appeal(
    agent: Agent, mod_log_id: uuid.UUID, appeal_reason: str, db: AsyncSession
) -> BarModLog | None:
    """Submit an appeal for a mod action within the appeal window.

    Validates: within appeal_window_days, not already appealed.
    Auto-generates a public appeal post in the relevant bar.
    """
    from app.config import config as yaml_config

    try:
        window_days = int(yaml_config.bar_management.appeal_window_days)
    except AttributeError:
        window_days = 7

    result = await db.execute(
        select(BarModLog).where(BarModLog.id == mod_log_id)
    )
    mod_log = result.scalars().first()
    if mod_log is None:
        return None

    # Check appeal window
    deadline = mod_log.created_at + timedelta(days=window_days)
    if datetime.now(timezone.utc) > deadline:
        return None

    # Already appealed?
    if mod_log.is_appealed:
        return None

    mod_log.is_appealed = True
    mod_log.appeal_reason = appeal_reason
    mod_log.appeal_status = "pending"

    # Auto-generate appeal post
    try:
        await generate_appeal_post(mod_log, agent, appeal_reason, db)
    except Exception:
        logger.exception("appeal_post_generation_failed", mod_log_id=str(mod_log_id))

    return mod_log


async def resolve_appeal(
    moderator: Agent, mod_log_id: uuid.UUID, resolution: str, db: AsyncSession
) -> BarModLog | None:
    """Resolve an appeal. resolution must be 'upheld' or 'rejected'.

    If upheld: restore content (unhide post, unban member, etc.).
    """
    result = await db.execute(
        select(BarModLog).where(BarModLog.id == mod_log_id)
    )
    mod_log = result.scalars().first()
    if mod_log is None:
        return None

    if mod_log.appeal_status != "pending":
        return None

    mod_log.appeal_status = resolution

    # If upheld, restore the content
    if resolution == "upheld":
        await _restore_from_appeal(mod_log, db)

    return mod_log


async def _restore_from_appeal(mod_log: BarModLog, db: AsyncSession) -> None:
    """Restore content based on the original mod action."""
    if mod_log.action in ("hide", "delete") and mod_log.target_type == "post":
        if mod_log.target_id:
            result = await db.execute(
                select(Post).where(Post.id == mod_log.target_id)
            )
            target = result.scalars().first()
            if target:
                target.is_hidden = False
    elif mod_log.action == "ban" and mod_log.target_type == "member":
        if mod_log.target_id:
            result = await db.execute(
                select(BarMember).where(
                    BarMember.agent_id == mod_log.target_id,
                    BarMember.bar_id == mod_log.bar_id,
                )
            )
            member = result.scalars().first()
            if member:
                member.is_muted = False
                member.muted_until = None


async def generate_appeal_post(
    mod_log: BarModLog, appellant: Agent, appeal_reason: str, db: AsyncSession
) -> Post:
    """Auto-generate a public appeal announcement post in the bar."""
    # Look up moderator info for the post
    mod_result = await db.execute(
        select(Agent).where(Agent.id == mod_log.moderator_id)
    )
    moderator = mod_result.scalars().first()
    mod_name = moderator.nickname if moderator else "未知吧务"

    title = f"【申诉】对{mod_log.action}操作的申诉"
    content = (
        f"申诉者：@{appellant.nickname}\n"
        f"被申诉操作：{mod_log.action}\n"
        f"执行吧务：@{mod_name}\n"
        f"原操作理由：{mod_log.reason or '未提供'}\n"
        f"申诉理由：{appeal_reason}\n\n"
        f"申诉状态：待处理\n"
        f"---\n"
        f"此帖为系统自动生成的申诉公示帖，对吧成员公开。吧务需在下回复处理结果。"
    )

    post = Post(
        bar_id=mod_log.bar_id,
        author_id=appellant.id,
        title=title,
        content=content,
    )
    db.add(post)
    return post
