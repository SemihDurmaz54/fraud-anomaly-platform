"""Platform servisi: skorlama, context adjust, rule engine ve RAG bileşenlerini tek noktada birleştirir.
API (Adım 10) ve agent'lar (Adım 9) bu sınıfı kullanır. Bileşenler ilk kullanımda (lazy) yüklenir."""
from __future__ import annotations

import os
from copy import deepcopy
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .context_engine import ContextEngine
from .llm import get_llm
from .rag import RAGPipeline
from .rag.embeddings import get_embedder
from .rule_engine import RuleEngine
from .scoring import LAYERS, OnlineScorer

RAW_FIELDS = ["TransactionID", "TransactionDT", "TransactionAmt", "ProductCD", "card1", "card4", "card6",
              "addr1", "dist1", "P_emaildomain", "R_emaildomain", "DeviceType"]


def _clean(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


class FraudService:
    def __init__(self, settings_path: str | Path = "config/settings.yaml", base_dir: str | Path | None = None):
        # proje kökü: açıkça verilmediyse FRAUDAI_HOME, o da yoksa paketin bir üst klasörü
        self.base = Path(base_dir or os.getenv("FRAUDAI_HOME") or Path(__file__).resolve().parents[1])
        sp = Path(settings_path)
        self.settings = yaml.safe_load((sp if sp.is_absolute() else self.base / sp).read_text(encoding="utf-8"))

    def path(self, key: str) -> Path:
        return self.base / self.settings["paths"][key]

    # ------------------------------------------------------------------ bileşenler
    @cached_property
    def scorer(self) -> OnlineScorer:
        return OnlineScorer.load(self.path("scoring_bundle"), self.path("entity_state"))

    @cached_property
    def context(self) -> ContextEngine:
        return ContextEngine.from_yaml(self.path("context_rules"))

    @cached_property
    def rules(self) -> RuleEngine:
        return RuleEngine.from_file(self.path("rules"))

    @cached_property
    def store(self) -> pd.DataFrame:
        return pd.read_parquet(self.path("tx_context")).set_index("TransactionID")

    @cached_property
    def rag(self) -> RAGPipeline:
        s = self.settings
        llm = get_llm(model=s["llm"]["model"], host=s["llm"]["host"])
        emb = get_embedder(model=s["embeddings"]["model"], host=s["llm"]["host"])
        return RAGPipeline(self.path("knowledge_base"), embedder=emb, llm=llm, k=s["rag"]["top_k"],
                           index_dir=self.path("rag_index")).build_index()

    def reload_rules(self) -> int:
        self.__dict__.pop("rules", None)
        self.__dict__.pop("context", None)
        return len(self.rules.rules)

    # ------------------------------------------------------------------ kayıt hazırlama
    def record_from_id(self, transaction_id: int) -> dict:
        if transaction_id not in self.store.index:
            raise KeyError(f"TransactionID {transaction_id} bulunamadı")
        rec = {k: _clean(v) for k, v in self.store.loc[transaction_id].to_dict().items()}
        rec["TransactionID"] = int(transaction_id)
        rec["source"] = "batch"
        return rec

    def record_from_transaction(self, tx: dict, update_state: bool = False) -> dict:
        res = self.scorer.score(tx, update=update_state)
        rec = {k: _clean(tx.get(k)) for k in RAW_FIELDS if k in tx}
        rec.update({k: _clean(v) for k, v in res["features"].items()})
        for k in LAYERS:
            rec[f"{k}_score_norm"] = res["layer_scores"][k]
            rec[f"{k}_reason"] = res["layer_reasons"][k]
        rec.update(raw_anomaly_score=res["raw_anomaly_score"], dominant_layer=res["dominant_layer"], source="online")
        return rec

    def resolve(self, transaction_id: int | None = None, transaction: dict | None = None,
                update_state: bool = False) -> dict:
        if transaction is not None:
            return self.record_from_transaction(transaction, update_state)
        if transaction_id is not None:
            return self.record_from_id(transaction_id)
        raise ValueError("transaction_id veya transaction verilmeli")

    def risk_level(self, score: float) -> str:
        r = self.settings["risk_levels"]
        return "high" if score >= r["high"] else "medium" if score >= r["medium"] else "low"

    # ------------------------------------------------------------------ işlemler
    def score(self, **kw) -> dict:
        rec = self.resolve(**kw)
        ctx = self.context.explain_one(rec)
        return {
            "transaction_id": rec.get("TransactionID"), "source": rec["source"],
            "raw_anomaly_score": rec["raw_anomaly_score"],
            "layer_scores": {k: rec[f"{k}_score_norm"] for k in LAYERS},
            "dominant_layer": rec["dominant_layer"],
            "context_factor": ctx["context_factor"], "adjusted_score": ctx["adjusted_score"],
            "risk_level": self.risk_level(ctx["adjusted_score"]),
            "applied_context_rules": [c["id"] for c in ctx["applied_rules"]],
        }

    def full_record(self, rec: dict) -> tuple[dict, dict]:
        """Context adjust uygulanmış ve türetilmiş bağlam alanları eklenmiş kayıt."""
        ctx = self.context.explain_one(rec)
        full = {**rec, **ctx["derived_context"], "adjusted_score": ctx["adjusted_score"],
                "context_factor": ctx["context_factor"]}
        return full, ctx

    def explain(self, include_rag: bool = False, **kw) -> dict:
        rec = self.resolve(**kw)
        full, ctx = self.full_record(rec)
        reasons = {k: rec.get(f"{k}_reason") for k in LAYERS}
        rules = self.rules.evaluate(full, ai_reasons=reasons)
        out = {
            "transaction_id": rec.get("TransactionID"), "source": rec["source"],
            "summary": f"{rules['decision']} | nihai risk {rules['final_risk_score']} "
                       f"(AI {rec['raw_anomaly_score']} → context {ctx['adjusted_score']} → kurallar "
                       f"{rules['rule_score_delta']:+.0f}) | karar veren: {rules['decided_by']}",
            "anomaly": {"raw_anomaly_score": rec["raw_anomaly_score"], "dominant_layer": rec["dominant_layer"],
                        "layers": {k: {"score": rec[f"{k}_score_norm"], "reason": reasons[k]} for k in LAYERS}},
            "context": ctx,
            "rules": rules,
            "key_features": {k: _clean(full.get(k)) for k in (
                "TransactionAmt", "ProductCD", "local_hour", "is_weekend", "uid_tx_count_past", "uid_age_days",
                "amt_to_uid_avg_past", "uid_tx_last_1h", "uid_tx_last_24h", "is_new_device_for_uid",
                "is_new_email_for_uid", "card_age_days", "addr1", "P_emaildomain", "R_emaildomain")},
        }
        if include_rag:
            out["rag"] = self.rag.reason_transaction(self.rag_input(out))
        return out

    @staticmethod
    def rag_input(ex: dict) -> dict:
        r = ex["rules"]
        return {"decision": r["decision"], "decided_by": r["decided_by"], "final_risk_score": r["final_risk_score"],
                "raw_anomaly_score": ex["anomaly"]["raw_anomaly_score"],
                "adjusted_score": ex["context"]["adjusted_score"], "fired_rules": r["fired_rules"],
                "context_rules": ex["context"]["applied_rules"], "ai_layer_reasons": r["ai_layer_reasons"]}

    def evaluate_rules(self, record: dict, extra_rules: list[dict] | None = None,
                       conflict_resolution: str | None = None, only_extra: bool = False) -> dict:
        engine = self.rules
        if extra_rules or conflict_resolution or only_extra:
            cfg = {"settings": {**engine.settings}, "rules": [] if only_extra else deepcopy(engine.rules)}
            if conflict_resolution:
                cfg["settings"]["conflict_resolution"] = conflict_resolution
            engine = RuleEngine(cfg)
            for r in extra_rules or []:
                engine.add_rule(r)
        rec = dict(record)
        if "raw_anomaly_score" in rec and "adjusted_score" not in rec:
            rec, _ = self.full_record(rec)
        else:
            rec = {**rec, **{k: int(v.iloc[0]) for k, v in self.context.add_derived(pd.DataFrame([rec]))
                             [list(self.context.derived)].items()}}
        return engine.evaluate(rec)

    def rag_query(self, question: str, transaction_id: int | None = None, k: int | None = None) -> dict:
        tx, rq = None, None
        if transaction_id is not None:
            # İşlem bağlamı: açıklama prompt'a eklenir, tetiklenen kurallar retrieval sorgusunu zenginleştirir
            ex = self.explain(transaction_id=transaction_id)
            tx = ex["summary"]
            sig = " ".join(f"{r['id']} {r['name']} {' '.join(r.get('tags', []))}" for r in ex["rules"]["fired_rules"])
            rq = f"{question} {sig} {ex['rules']['decision']}"
        return self.rag.answer(question, k=k, transaction=tx, retrieval_query=rq)

    def rule_list(self) -> list[dict]:
        return self.rules.rules

    def add_rule(self, rule: dict) -> dict:
        self.rules.add_rule(rule)
        return self.rules.validate_rule(rule)

    def remove_rule(self, rule_id: str) -> None:
        if not any(r["id"] == rule_id for r in self.rules.rules):
            raise KeyError(rule_id)
        self.rules.remove_rule(rule_id)
