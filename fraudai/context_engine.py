"""Context Adjust Engine (Adım 6).

Ham anomali skorunu (0–100) iş ve zaman bağlamına göre yeniden ağırlıklandırır.
Kurallar `config/context_rules.yaml` dosyasından okunur; kod değişmeden yeni bağlam kuralı eklenebilir.

    adjusted_score = clip(raw_anomaly_score × Π factorᵢ, 0, 100)
    Π factorᵢ ∈ [min_factor, max_factor]  (tek başına hiçbir bağlam skoru sınırsız değiştiremez)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from . import conditions as C


class ContextEngine:
    def __init__(self, config: dict):
        self.config = config
        self.score_field = config.get("score_field", "raw_anomaly_score")
        b = config.get("bounds", {})
        self.min_factor, self.max_factor = b.get("min_factor", 0.5), b.get("max_factor", 1.5)
        self.derived = config.get("derived_fields", {})
        self.rules = [r for r in config.get("rules", []) if r.get("enabled", True)]
        for name, cond in self.derived.items():
            C.validate(cond, f"derived_fields.{name}")
        for r in self.rules:
            C.validate(r["condition"], f"{r['id']}.condition")
            if not (0 < float(r["factor"]) <= 3):
                raise ValueError(f"{r['id']}: factor (0, 3] aralığında olmalı")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ContextEngine":
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ toplu (vektörize)
    def add_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for name, cond in self.derived.items():  # sırayla: sonraki türetilmiş alanlar öncekileri kullanabilir
            out[name] = C.evaluate(cond, out).astype("int8")
        return out

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        """Her satır için context_factor, adjusted_score ve uygulanan kural listesini döndürür."""
        data = self.add_derived(df)
        factor = np.ones(len(data))
        hits = {}
        for r in self.rules:
            m = C.evaluate(r["condition"], data).to_numpy()
            factor[m] *= float(r["factor"])
            hits[r["id"]] = m
        factor = np.clip(factor, self.min_factor, self.max_factor)
        raw = data[self.score_field].to_numpy(dtype=float)
        H = np.column_stack(list(hits.values())) if hits else np.zeros((len(data), 0), bool)
        ids = np.array(list(hits.keys()))
        applied = [",".join(ids[row]) for row in H]
        res = pd.DataFrame({"context_factor": factor.round(4),
                            "adjusted_score": np.clip(raw * factor, 0, 100).round(2),
                            "context_rules": applied}, index=data.index)
        for name in self.derived:
            res[name] = data[name]
        return res

    # ------------------------------------------------------------------ tek kayıt (API / agent)
    def explain_one(self, record: dict[str, Any]) -> dict:
        data = self.add_derived(pd.DataFrame([record]))
        applied, factor = [], 1.0
        for r in self.rules:
            if bool(C.evaluate(r["condition"], data).iloc[0]):
                factor *= float(r["factor"])
                applied.append({"id": r["id"], "name": r["name"], "category": r.get("category"),
                                "factor": r["factor"], "condition": C.describe(r["condition"]),
                                "rationale": r.get("rationale", "")})
        clipped = float(np.clip(factor, self.min_factor, self.max_factor))
        raw = float(record[self.score_field])
        return {
            "raw_score": round(raw, 2),
            "context_factor": round(clipped, 4),
            "factor_was_clipped": not np.isclose(clipped, factor),
            "adjusted_score": round(float(np.clip(raw * clipped, 0, 100)), 2),
            "derived_context": {k: int(data[k].iloc[0]) for k in self.derived},
            "applied_rules": applied,
        }

    def documentation(self) -> pd.DataFrame:
        """Kuralların tablo hâlinde dokümantasyonu."""
        return pd.DataFrame([{"id": r["id"], "kategori": r.get("category"), "ad": r["name"],
                              "koşul": C.describe(r["condition"]), "çarpan": r["factor"],
                              "gerekçe": r.get("rationale", "")} for r in self.rules])
