from __future__ import annotations

from typing import Any, Callable

from .bus import Message, MessageBus


class Agent:
    """Temel agent. Alt sınıflar `capabilities` sözlüğünde görev adı → handler eşlemesi tanımlar."""
    description = ""

    def __init__(self, name: str):
        self.name = name
        self.bus: MessageBus | None = None
        self.capabilities: dict[str, Callable[[dict, Message], dict]] = {}

    # ------------------------------------------------------------------ alma
    def receive(self, msg: Message) -> Message:
        handler = self.capabilities.get(msg.task)
        try:
            if handler is None:
                raise LookupError(f"{self.name} '{msg.task}' görevini desteklemiyor")
            result = handler(msg.payload, msg)
            perf = "RESULT"
        except Exception as e:  # hata da bir mesajdır; çağıran agent karar verir
            result, perf = {"error": f"{type(e).__name__}: {e}"}, "FAILURE"
        return Message(self.name, msg.sender, perf, msg.task, result, msg.conversation_id, reply_to=msg.id)

    # ------------------------------------------------------------------ gönderme
    def ask(self, recipient: str, task: str, payload: dict, conv: str) -> dict[str, Any]:
        """Agent-to-agent istek (REQUEST)."""
        reply = self.bus.send(Message(self.name, recipient, "REQUEST", task, payload, conv))
        if reply.performative == "FAILURE":
            raise RuntimeError(reply.payload["error"])
        return reply.payload

    def delegate(self, task: str, payload: dict, conv: str) -> dict[str, Any]:
        """Görev devri (DELEGATE): görevi yapabilen agent bus kaydından bulunur."""
        reply = self.bus.send(Message(self.name, self.bus.find(task), "DELEGATE", task, payload, conv))
        if reply.performative == "FAILURE":
            raise RuntimeError(reply.payload["error"])
        return reply.payload
