"""VK State Manager - In-memory state management for VK users (Redis optional)"""
import logging
import json
from typing import Dict, Any, Optional

class VKStateManager:
    """Manages FSM-like states for VK users using Redis"""

    def __init__(self, redis: Redis):
        self.redis = redis
        self.prefix = "vk_user_state:"
        self._memory_state: Dict[int, str] = {}
        self._memory_data: Dict[int, Dict[str, Any]] = {}
        self._redis_available = True

    def _disable_redis(self, error: Exception) -> None:
        if self._redis_available:
            logging.warning(
                f"VK Redis unavailable, switching to in-memory state: {error}"
            )
        self._redis_available = False

    async def set_state(self, user_id: int, state: str) -> None:
        """Set user state"""
        if not self._redis_available:
            self._memory_state[user_id] = state
            logging.debug(f"VK State set (memory): {user_id} -> {state}")
            return

        key = f"{self.prefix}{user_id}"
        try:
            await self.redis.set(key, state, ex=86400)  # 24 hours expiry
            logging.debug(f"VK State set: {user_id} -> {state}")
        except Exception as e:
            self._disable_redis(e)
            self._memory_state[user_id] = state
            logging.debug(f"VK State set (memory): {user_id} -> {state}")

    async def get_state(self, user_id: int) -> Optional[str]:
        """Get current user state"""
        if not self._redis_available:
            return self._memory_state.get(user_id)

        key = f"{self.prefix}{user_id}"
        try:
            state = await self.redis.get(key)
            return state.decode() if state else None
        except Exception as e:
            self._disable_redis(e)
            return self._memory_state.get(user_id)

    async def clear_state(self, user_id: int) -> None:
        """Clear user state"""
        if not self._redis_available:
            self._memory_state.pop(user_id, None)
            logging.debug(f"VK State cleared (memory): {user_id}")
            return

        key = f"{self.prefix}{user_id}"
        try:
            await self.redis.delete(key)
            logging.debug(f"VK State cleared: {user_id}")
        except Exception as e:
            self._disable_redis(e)
            self._memory_state.pop(user_id, None)
            logging.debug(f"VK State cleared (memory): {user_id}")

    async def set_data(self, user_id: int, data: Dict[str, Any]) -> None:
        """Store user data (like form data before processing)"""
        if not self._redis_available:
            self._memory_data[user_id] = data
            logging.debug(f"VK Data set (memory): {user_id}")
            return

        key = f"vk_user_data:{user_id}"
        json_data = json.dumps(data)
        try:
            await self.redis.set(key, json_data, ex=3600)  # 1 hour expiry
            logging.debug(f"VK Data set: {user_id}")
        except Exception as e:
            self._disable_redis(e)
            self._memory_data[user_id] = data
            logging.debug(f"VK Data set (memory): {user_id}")

    async def get_data(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get stored user data"""
        if not self._redis_available:
            return self._memory_data.get(user_id, {})

        key = f"vk_user_data:{user_id}"
        try:
            data = await self.redis.get(key)
            return json.loads(data.decode()) if data else {}
        except Exception as e:
            self._disable_redis(e)
            return self._memory_data.get(user_id, {})

    async def clear_data(self, user_id: int) -> None:
        """Clear user data"""
        if not self._redis_available:
            self._memory_data.pop(user_id, None)
            return

        key = f"vk_user_data:{user_id}"
        try:
            await self.redis.delete(key)
        except Exception as e:
            self._disable_redis(e)
            self._memory_data.pop(user_id, None)
