import asyncio
from typing import Any, Dict, List, Union
from aiogram import BaseMiddleware
from aiogram.types import Message

class AlbumMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.5):
        self.latency = latency
        self.album_data: Dict[str, List[Message]] = {}

    async def __call__(self, handler, event: Message, data: Dict[str, Any]):
        if not event.media_group_id:
            return await handler(event, data)

        try:
            self.album_data[event.media_group_id].append(event)
        except KeyError:
            self.album_data[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)

            data['_is_last'] = True
            data['album'] = self.album_data.pop(event.media_group_id)
            return await handler(event, data)