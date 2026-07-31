"""事件发布器接口。

EventPublisher 负责将 RuntimeEvent 发布到 EventStore 和实时订阅者。
Agent Loop 通过它发布事件，不关心持久化和推送细节。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.runtime.events import RuntimeEvent


@runtime_checkable
class EventPublisher(Protocol):
    """事件发布器接口。

    职责：
    1. 持久化事件到 EventStore（persisted=True 的事件）
    2. 推送给实时订阅者（SSE/WebSocket）
    3. 保证单 Run 内事件有序（sequence）
    """

    async def publish(self, event: RuntimeEvent) -> None:
        """发布一个事件。

        Args:
            event: 要发布的 RuntimeEvent。
        """
        ...  # pragma: no cover
