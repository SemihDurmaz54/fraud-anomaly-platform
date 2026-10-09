"""Basit, bağımlılıksız vector store: L2-normalize vektörlerde kosinüs benzerliği (iç çarpım).
Küçük/orta bilgi tabanları için yeterli; büyük ölçekte FAISS/Chroma ile aynı arayüz korunarak değiştirilebilir."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class VectorStore:
    def __init__(self):
        self.vectors: np.ndarray | None = None
        self.items: list[dict] = []

    def add(self, items: list[dict], vectors: np.ndarray) -> None:
        assert len(items) == len(vectors)
        self.items.extend(items)
        self.vectors = vectors if self.vectors is None else np.vstack([self.vectors, vectors])

    def __len__(self):
        return len(self.items)

    def search(self, qvec: np.ndarray, k: int = 4, where: dict | None = None) -> list[dict]:
        """Top-k kosinüs benzerliği. `where` ile metadata filtresi (ör. {"doc_id": "03_..."})."""
        sims = self.vectors @ qvec.ravel()
        idx = np.argsort(-sims)
        out = []
        for i in idx:
            it = self.items[i]
            if where and any(it.get(k_) != v for k_, v in where.items()):
                continue
            out.append({**it, "score": float(sims[i])})
            if len(out) == k:
                break
        return out

    def save(self, path: str | Path) -> None:
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        (path / "items.json").write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "VectorStore":
        path = Path(path); s = cls()
        s.vectors = np.load(path / "vectors.npy")
        s.items = json.loads((path / "items.json").read_text(encoding="utf-8"))
        return s
