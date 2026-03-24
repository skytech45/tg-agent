"""
memory/redis_memory.py — Per-user stateful memory backed by Redis.

Each user gets a namespaced key storing:
  - role (client / agent / admin)
  - conversation history (last N messages)
  - session state (current flow step)
  - metadata (join date, payment status, etc.)
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from config import settings

# Max messages kept per user in rolling history
MAX_HISTORY = 20
# TTL for user context (30 days)
USER_TTL = 60 * 60 * 24 * 30


class UserMemory:
    """Manages per-user state and conversation history in Redis."""

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client

    def _key(self, user_id: int) -> str:
        return f"tg_agent:user:{user_id}"

    async def get(self, user_id: int) -> Dict[str, Any]:
        """Fetch full user context. Returns defaults if user is new."""
        raw = await self.redis.get(self._key(user_id))
        if raw:
            return json.loads(raw)
        return {
            "user_id": user_id,
            "role": "client",
            "flow_state": None,
            "payment_verified": False,
            "joined_at": datetime.utcnow().isoformat(),
            "history": [],
            "metadata": {},
        }

    async def save(self, user_id: int, data: Dict[str, Any]) -> None:
        """Persist user context with TTL refresh."""
        await self.redis.set(self._key(user_id), json.dumps(data), ex=USER_TTL)

    async def set_role(self, user_id: int, role: str) -> None:
        """Update user role (client / agent / admin)."""
        data = await self.get(user_id)
        data["role"] = role
        await self.save(user_id, data)

    async def set_flow_state(self, user_id: int, state: Optional[str]) -> None:
        """Set current flow step for multi-step interactions."""
        data = await self.get(user_id)
        data["flow_state"] = state
        await self.save(user_id, data)

    async def set_payment_verified(self, user_id: int, verified: bool) -> None:
        """Mark user payment as verified or rejected."""
        data = await self.get(user_id)
        data["payment_verified"] = verified
        data["metadata"]["payment_verified_at"] = datetime.utcnow().isoformat() if verified else None
        await self.save(user_id, data)

    async def append_message(self, user_id: int, role: str, content: str) -> None:
        """Add a message to the rolling conversation history."""
        data = await self.get(user_id)
        history: List[Dict] = data.get("history", [])
        history.append({
            "role": role,
            "content": content,
            "ts": datetime.utcnow().isoformat(),
        })
        # Keep only the last MAX_HISTORY messages
        data["history"] = history[-MAX_HISTORY:]
        await self.save(user_id, data)

    async def get_history(self, user_id: int) -> List[Dict[str, str]]:
        """Return conversation history formatted for OpenAI."""
        data = await self.get(user_id)
        return [{"role": m["role"], "content": m["content"]} for m in data.get("history", [])]

    async def update_metadata(self, user_id: int, **kwargs: Any) -> None:
        """Merge arbitrary key-value pairs into user metadata."""
        data = await self.get(user_id)
        data["metadata"].update(kwargs)
        await self.save(user_id, data)

    async def delete(self, user_id: int) -> None:
        """Wipe all data for a user (admin action)."""
        await self.redis.delete(self._key(user_id))


async def get_redis() -> aioredis.Redis:
    """Create and return an async Redis client."""
    return await aioredis.from_url(settings.redis_url, decode_responses=True)
