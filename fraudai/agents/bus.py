"""Agent'lar arası iletişim altyapısı: mesaj formatı ve mesaj yolu (message bus).

Her mesaj bir *performative* (iletişim eylemi) taşır:
  DELEGATE : orkestratörün bir görevi yetkin agent'a devretmesi
  REQUEST  : bir agent'ın başka bir agent'tan bilgi/iş istemesi (agent-to-agent)
  RESULT   : başarılı cevap          FAILURE: hata cevabı
Bus, yetenek (capability) kaydını tutar; görevin hangi agent'a gideceği buradan bulunur (task routing).
Tüm mesajlar log'lanır; böylece iş akışı uçtan uca izlenebilir (trace).
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

_ids = itertools.count(1)


@dataclass
class Message:
    sender: str
    recipient: str
    performative: str
    task: str
    payload: dict[str, Any] = field(default_factory=dict)
    conversation_id: str = ""
    reply_to: int | None = None
    id: int = field(default_factory=lambda: next(_ids))
    ts: float = field(default_factory=time.time)
    depth: int = 0


class MessageBus:
    def __init__(self):
        self.agents: dict[str, Any] = {}
        self.registry: dict[str, str] = {}
        self.log: list[Message] = []
        self._depth = 0

    def register(self, agent) -> None:
        self.agents[agent.name] = agent
        agent.bus = self
        for cap in agent.capabilities:
            if cap in self.registry:
                raise ValueError(f"'{cap}' yeteneği zaten {self.registry[cap]} agent'ına kayıtlı")
            self.registry[cap] = agent.name

    def find(self, capability: str) -> str:
        if capability not in self.registry:
            raise LookupError(f"'{capability}' görevini yapabilen agent yok")
        return self.registry[capability]

    def send(self, msg: Message) -> Message:
        if msg.recipient not in self.agents:
            raise LookupError(f"Alıcı agent bulunamadı: {msg.recipient}")
        msg.depth = self._depth
        self.log.append(msg)
        self._depth += 1
        try:
            reply = self.agents[msg.recipient].receive(msg)
        finally:
            self._depth -= 1
        reply.depth = self._depth
        self.log.append(reply)
        return reply

    def directory(self) -> pd.DataFrame:
        return pd.DataFrame([{"agent": a.name, "rol": a.description, "yetenekler": ", ".join(a.capabilities)}
                             for a in self.agents.values()])

    def trace(self, conversation_id: str | None = None) -> pd.DataFrame:
        rows = []
        for m in self.log:
            if conversation_id and m.conversation_id != conversation_id:
                continue
            rows.append({"#": m.id, "akış": "   " * m.depth + f"{m.sender} → {m.recipient}",
                         "performative": m.performative, "görev": m.task, "özet": _summary(m.payload)})
        return pd.DataFrame(rows)


def _summary(p: dict) -> str:
    if not p:
        return ""
    if "error" in p:
        return f"HATA: {p['error']}"
    keys = ("decision", "final_risk_score", "adjusted_score", "raw_anomaly_score", "recommendation", "n_sources",
            "transaction_id", "question", "n_features")
    parts = [f"{k}={p[k]}" for k in keys if k in p and p[k] is not None]
    return ", ".join(parts)[:120] or ", ".join(list(p)[:5])
