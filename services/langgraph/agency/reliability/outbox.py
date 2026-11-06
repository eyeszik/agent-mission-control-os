from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import OutboxMessage, OutboxStatus
from .service import ProductionTrustKernel, ReliabilityError


class OutboxDispatchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OutboxDeliveryResult:
    message_id: str
    status: str
    result_ref: str | None = None
    error: str | None = None


class OutboxDispatcher:
    """Bounded dispatcher for durable outbox messages.

    Delivery authority is injected by the canonical repository. This class does
    not infer permissions and never dispatches a message that has already been
    delivered. Retries are capped by the persisted message attempt counter.
    """

    def __init__(
        self,
        kernel: ProductionTrustKernel,
        *,
        authorize_delivery: Callable[[OutboxMessage], bool],
        max_batch: int = 25,
    ) -> None:
        if max_batch <= 0:
            raise ValueError("max_batch must be positive")
        self.kernel = kernel
        self.authorize_delivery = authorize_delivery
        self.max_batch = max_batch
        self.handlers: dict[str, Callable[[OutboxMessage], str | None]] = {}

    def register(self, topic: str, handler: Callable[[OutboxMessage], str | None]) -> None:
        if not topic:
            raise ValueError("topic is required")
        if topic in self.handlers:
            raise OutboxDispatchError("topic handler already registered")
        self.handlers[topic] = handler

    def dispatch_one(self, *, message_id: str, worker_id: str) -> OutboxDeliveryResult:
        message = self.kernel.store.state.outbox.get(message_id)
        if message is None:
            raise ReliabilityError("UNKNOWN_OUTBOX_MESSAGE")
        if message.status == OutboxStatus.DELIVERED:
            return OutboxDeliveryResult(message_id=message_id, status="ALREADY_DELIVERED")
        if not self.authorize_delivery(message):
            return OutboxDeliveryResult(message_id=message_id, status="BLOCKED_AUTHORITY")
        handler = self.handlers.get(message.topic)
        if handler is None:
            return OutboxDeliveryResult(message_id=message_id, status="BLOCKED_NO_HANDLER")
        claimed = self.kernel.claim_outbox(message_id=message_id, worker_id=worker_id)
        try:
            result_ref = handler(claimed)
        except Exception as exc:
            self.kernel.mark_outbox_failed(message_id=message_id, error=type(exc).__name__)
            return OutboxDeliveryResult(message_id=message_id, status="FAILED", error=type(exc).__name__)
        self.kernel.mark_outbox_delivered(message_id=message_id)
        return OutboxDeliveryResult(message_id=message_id, status="DELIVERED", result_ref=result_ref)

    def dispatch_pending(self, *, worker_id: str) -> tuple[OutboxDeliveryResult, ...]:
        messages = [m for m in self.kernel.store.state.outbox.values() if m.status != OutboxStatus.DELIVERED]
        messages.sort(key=lambda item: (item.created_at, item.message_id))
        results: list[OutboxDeliveryResult] = []
        for message in messages[: self.max_batch]:
            try:
                results.append(self.dispatch_one(message_id=message.message_id, worker_id=worker_id))
            except ReliabilityError as exc:
                results.append(OutboxDeliveryResult(message_id=message.message_id, status="BLOCKED", error=str(exc)))
        return tuple(results)
