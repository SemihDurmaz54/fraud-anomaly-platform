"""Embedding üretimi: Ollama üzerinden local embedding modeli (varsayılan ``bge-m3``; çok dilli, Türkçe için uygun).

Ollama'ya ulaşılamazsa veya model yüklü değilse kurulum talimatıyla birlikte hata verilir.
"""
from __future__ import annotations

import os

import httpx
import numpy as np

from ..llm import OllamaNotAvailable, setup_hint

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")


def _l2(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-12)


class OllamaEmbedder:
    # RAG'de alakasız kaynakları elemek için kosinüs benzerliği eşiği (bge-m3 ölçeğinde;
    # testte bilgi tabanı dışı bir soruda en yüksek skor ~0,54, ilgili kaynaklarda 0,60+ görüldü)
    min_score = 0.50

    def __init__(self, model: str = DEFAULT_EMBED_MODEL, host: str = DEFAULT_HOST):
        self.model, self.host = model, host.rstrip("/")
        self.name = f"ollama:{model}"
        self.endpoint = "embed"

    def check(self) -> "OllamaEmbedder":
        """İlk çağrıda model belleğe yüklendiği için zaman aşımı uzun tutuldu.
        Yeni Ollama sürümleri /api/embed, eski sürümler /api/embeddings kullanır; ikisi de denenir."""
        errors = []
        for endpoint in ("embed", "embeddings"):
            try:
                self.endpoint = endpoint
                self.encode(["test"])
                return self
            except Exception as e:
                errors.append(f"/api/{endpoint}: {type(e).__name__}: {e}")
        raise OllamaNotAvailable(f"'{self.model}' embedding modeli kullanılamıyor ({'; '.join(errors)})"
                                 f"{setup_hint(self.model, self.host)}")

    def fit(self, texts: list[str]) -> "OllamaEmbedder":
        return self  # önceden eğitilmiş model

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.endpoint == "embed":
            r = httpx.post(f"{self.host}/api/embed", json={"model": self.model, "input": texts}, timeout=300)
            r.raise_for_status()
            vecs = r.json()["embeddings"]
        else:  # eski Ollama API: her metin için ayrı çağrı
            vecs = []
            for t in texts:
                r = httpx.post(f"{self.host}/api/embeddings", json={"model": self.model, "prompt": t}, timeout=300)
                r.raise_for_status()
                vecs.append(r.json()["embedding"])
        return _l2(np.asarray(vecs, dtype="float32"))


def get_embedder(model: str = DEFAULT_EMBED_MODEL, host: str = DEFAULT_HOST) -> OllamaEmbedder:
    return OllamaEmbedder(model=model, host=host).check()
