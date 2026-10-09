"""Local LLM istemcisi (Ollama, http://localhost:11434). Varsayılan model ``qwen2.5:3b``.

Model adı ve adres `config/settings.yaml` veya `OLLAMA_MODEL` / `OLLAMA_HOST` ortam değişkenleriyle değiştirilebilir.
Ollama'ya ulaşılamazsa veya model yüklü değilse kurulum talimatıyla birlikte hata verilir.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")


class OllamaNotAvailable(RuntimeError):
    pass


def setup_hint(model: str, host: str) -> str:
    return (f"\n  1) Ollama'yı kurun: https://ollama.com/download"
            f"\n  2) Ollama'nın çalıştığından emin olun (ör. `ollama list` komutu cevap vermeli; adres: {host})"
            f"\n  3) Modeli indirin: `ollama pull {model}`")


class OllamaLLM:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, temperature: float = 0.1,
                 timeout: float = 180):
        self.model, self.host, self.temperature, self.timeout = model, host.rstrip("/"), temperature, timeout
        self.name = f"ollama:{model}"

    def check(self) -> "OllamaLLM":
        """Ollama'ya ulaşılabildiğini ve modelin yüklü olduğunu doğrular; değilse talimatla hata verir."""
        try:
            r = httpx.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
        except Exception as e:
            raise OllamaNotAvailable(f"Ollama'ya ulaşılamadı ({self.host}): {e}{setup_hint(self.model, self.host)}")
        names = {m["name"] for m in r.json().get("models", [])}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise OllamaNotAvailable(f"'{self.model}' modeli Ollama'da yüklü değil. Yüklü modeller: "
                                     f"{sorted(names) or 'yok'}{setup_hint(self.model, self.host)}")
        return self

    def generate(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        body: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False,
                                "options": {"temperature": self.temperature}}
        if system:
            body["system"] = system
        if json_mode:
            body["format"] = "json"
        r = httpx.post(f"{self.host}/api/generate", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["response"].strip()


def get_llm(model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST) -> OllamaLLM:
    return OllamaLLM(model=model, host=host).check()


def parse_json(text: str) -> dict:
    """LLM çıktısından JSON nesnesini güvenli biçimde çıkarır."""
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"raw_text": text}
