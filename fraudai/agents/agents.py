"""Multi-agent fraud inceleme sistemi (Adım 9).

Agent'lar ve yetenekleri:

| Agent              | Yetenek (görev)                         | Ne yapar                                                  |
|--------------------|-----------------------------------------|-----------------------------------------------------------|
| OrchestratorAgent  | analyze_transaction                     | Planı çıkarır, görevleri devreder, sonucu birleştirir      |
| FeatureAgent       | features                                | Ham işlemden / kayıttan feature üretir                    |
| ScoringAgent       | score                                   | 4 katmanlı anomali skoru; feature yoksa FeatureAgent'a sorar |
| ContextAgent       | context_adjust                          | İş/zaman bağlamına göre skoru düzeltir                     |
| RuleAgent          | evaluate_rules                          | İş kurallarını çalıştırır, karar ve açıklama üretir       |
| KnowledgeAgent     | retrieve_policy, reason_transaction     | RAG: politika arama ve politika tabanlı değerlendirme      |
| InvestigatorAgent  | investigate                             | Vaka raporu yazar; politika için KnowledgeAgent'a sorar   |

Görev devri (delegation): Orkestratör hangi agent'ın hangi görevi yaptığını bilmez; görevi bus'a
devreder, bus yetenek kaydından doğru agent'ı bulur. Agent'lar ihtiyaç duyduklarında birbirlerine
doğrudan istek gönderir (ör. ScoringAgent → FeatureAgent, InvestigatorAgent → KnowledgeAgent).
"""
from __future__ import annotations

import json
import uuid

from ..llm import parse_json
from ..scoring import LAYERS
from ..service import RAW_FIELDS, FraudService, _clean
from .base import Agent
from .bus import MessageBus

DEFAULT_PLAN = ["score", "context_adjust", "evaluate_rules", "investigate"]


class FeatureAgent(Agent):
    description = "Feature engineering"

    def __init__(self, svc: FraudService):
        super().__init__("FeatureAgent"); self.svc = svc
        self.capabilities = {"features": self.features}

    def features(self, p, msg):
        if p.get("transaction") is not None:
            tx = p["transaction"]
            f = self.svc.scorer.features(tx)
            rec = {**{k: _clean(tx.get(k)) for k in RAW_FIELDS if k in tx}, **{k: _clean(v) for k, v in f.items()}}
        else:
            rec = self.svc.record_from_id(p["transaction_id"])
            rec = {k: v for k, v in rec.items() if not k.endswith(("_score_norm", "_reason"))
                   and k not in ("raw_anomaly_score", "dominant_layer")}
        return {"features": rec, "n_features": len(rec)}


class ScoringAgent(Agent):
    description = "Çok katmanlı anomali skorlama"

    def __init__(self, svc: FraudService):
        super().__init__("ScoringAgent"); self.svc = svc
        self.capabilities = {"score": self.score}

    def score(self, p, msg):
        feats = p.get("features") or self.ask("FeatureAgent", "features", p, msg.conversation_id)["features"]
        if p.get("transaction") is not None:
            res = self.svc.scorer.score(p["transaction"], update=False)
            layers, reasons = res["layer_scores"], res["layer_reasons"]
            raw, dom = res["raw_anomaly_score"], res["dominant_layer"]
        else:
            rec = self.svc.record_from_id(p["transaction_id"])
            layers = {k: rec[f"{k}_score_norm"] for k in LAYERS}
            reasons = {k: rec[f"{k}_reason"] for k in LAYERS}
            raw, dom = rec["raw_anomaly_score"], rec["dominant_layer"]
        record = {**feats, **{f"{k}_score_norm": layers[k] for k in LAYERS},
                  **{f"{k}_reason": reasons[k] for k in LAYERS}, "raw_anomaly_score": raw, "dominant_layer": dom}
        return {"record": record, "raw_anomaly_score": raw, "layer_scores": layers, "layer_reasons": reasons,
                "dominant_layer": dom}


class ContextAgent(Agent):
    description = "Context-aware skor düzeltme"

    def __init__(self, svc: FraudService):
        super().__init__("ContextAgent"); self.svc = svc
        self.capabilities = {"context_adjust": self.adjust}

    def adjust(self, p, msg):
        full, ctx = self.svc.full_record(p["record"])
        return {"record": full, "context": ctx, "adjusted_score": ctx["adjusted_score"]}


class RuleAgent(Agent):
    description = "İş kuralları (rule engine)"

    def __init__(self, svc: FraudService):
        super().__init__("RuleAgent"); self.svc = svc
        self.capabilities = {"evaluate_rules": self.evaluate}

    def evaluate(self, p, msg):
        rec = p["record"]
        out = self.svc.rules.evaluate(rec, ai_reasons={k: rec.get(f"{k}_reason") for k in LAYERS})
        return {**out}


class KnowledgeAgent(Agent):
    description = "RAG bilgi tabanı (politika arama ve gerekçelendirme)"

    def __init__(self, svc: FraudService):
        super().__init__("KnowledgeAgent"); self.svc = svc
        self.capabilities = {"retrieve_policy": self.retrieve, "reason_transaction": self.reason}

    def retrieve(self, p, msg):
        res = self.svc.rag.answer(p["question"], k=p.get("k"))
        return {"question": p["question"], "answer": res["answer"], "sources": res["sources"],
                "n_sources": len(res["sources"])}

    def reason(self, p, msg):
        res = self.svc.rag.reason_transaction(p["case"])
        return {**res, "n_sources": len(res["sources"]),
                "recommendation": res["assessment"].get("recommendation")}


class InvestigatorAgent(Agent):
    description = "Vaka analisti (LLM ile rapor)"

    def __init__(self, svc: FraudService):
        super().__init__("InvestigatorAgent"); self.svc = svc
        self.capabilities = {"investigate": self.investigate}

    def investigate(self, p, msg):
        conv = msg.conversation_id
        rules, ctx, anomaly = p["rules"], p["context"], p["anomaly"]
        case = {"decision": rules["decision"], "decided_by": rules["decided_by"],
                "final_risk_score": rules["final_risk_score"], "raw_anomaly_score": anomaly["raw_anomaly_score"],
                "adjusted_score": ctx["adjusted_score"], "fired_rules": rules["fired_rules"],
                "context_rules": ctx["applied_rules"], "ai_layer_reasons": anomaly["layer_reasons"]}
        rag = self.ask("KnowledgeAgent", "reason_transaction", {"case": case}, conv)
        # Eskalasyon kuralı için ek politika sorusu (agent-to-agent, koşullu)
        extra = None
        if rules["decision"] in ("REVIEW", "BLOCK"):
            extra = self.ask("KnowledgeAgent", "retrieve_policy",
                             {"question": f"{rules['decision']} kararı sonrası inceleme süresi ve eskalasyon", "k": 2},
                             conv)
        llm = self.svc.rag.llm
        a = rag["assessment"]
        prompt = ("Aşağıdaki fraud vakası için analist ekibine 4-5 cümlelik Türkçe bir özet yaz. "
                  "Yalnızca verilen bilgileri kullan.\n\n"
                  f"VAKA: {json.dumps(case, ensure_ascii=False, default=str)[:3000]}\n\n"
                  f"POLİTİKA DEĞERLENDİRMESİ: {json.dumps(a, ensure_ascii=False)[:2000]}")
        narrative = llm.generate(prompt)
        return {"recommendation": a.get("recommendation", rules["decision"]), "narrative": narrative,
                "policy_assessment": a, "grounded": rag["reasoning_steps"][-1]["grounded"],
                "escalation_policy": extra["answer"] if extra else None, "n_sources": rag["n_sources"]}


class OrchestratorAgent(Agent):
    description = "İş akışı yöneticisi (planlama ve görev devri)"

    def __init__(self, svc: FraudService, use_llm_planner: bool = True):
        super().__init__("Orchestrator"); self.svc = svc
        self.use_llm_planner = use_llm_planner
        self.capabilities = {"analyze_transaction": self.analyze}

    def plan(self) -> tuple[list[str], str]:
        llm = self.svc.rag.llm
        if self.use_llm_planner:
            agents = {cap: self.bus.agents[name].description for cap, name in self.bus.registry.items()
                      if cap not in ("analyze_transaction", "features", "retrieve_policy", "reason_transaction")}
            prompt = ("Bir fraud tespit iş akışı planla. Kullanılabilir görevler: "
                      f"{json.dumps(agents, ensure_ascii=False)}. Sıra: önce skor, sonra bağlam, sonra kurallar, "
                      'en son inceleme. Yalnızca {"plan": [görev adları]} JSON döndür.')
            plan = parse_json(llm.generate(prompt, json_mode=True)).get("plan", [])
            if isinstance(plan, list) and plan and all(t in self.bus.registry for t in plan) and plan[0] == "score":
                return plan, "llm"
        return list(DEFAULT_PLAN), "default"  # LLM planı geçersizse (bilinmeyen görev vb.) varsayılan plan

    def analyze(self, p, msg):
        conv = msg.conversation_id
        plan, plan_source = self.plan()
        state: dict = {"plan": plan, "plan_source": plan_source, "skipped": []}
        base = {k: p[k] for k in ("transaction_id", "transaction") if p.get(k) is not None}
        for task in plan:
            if task == "score":
                r = self.delegate("score", base, conv)
                state["anomaly"] = {k: r[k] for k in ("raw_anomaly_score", "layer_scores", "layer_reasons", "dominant_layer")}
                record = r["record"]
            elif task == "context_adjust":
                r = self.delegate("context_adjust", {"record": record}, conv)
                record, state["context"] = r["record"], r["context"]
            elif task == "evaluate_rules":
                state["rules"] = self.delegate("evaluate_rules", {"record": record}, conv)
            elif task == "investigate":
                rl = state["rules"]
                risky = [r for r in rl["fired_rules"] if r["action"] != "ALLOW"]
                if rl["decision"] == "APPROVE" and rl["final_risk_score"] < 50 and not risky:
                    state["skipped"].append("investigate (hızlı yol: düşük risk, risk kuralı tetiklenmedi)")
                    continue
                state["investigation"] = self.delegate("investigate", {k: state[k] for k in ("rules", "context", "anomaly")}, conv)
        rl = state["rules"]
        inv = state.get("investigation") or {}
        return {
            "transaction_id": p.get("transaction_id") or (p.get("transaction") or {}).get("TransactionID"),
            "decision": rl["decision"], "decided_by": rl["decided_by"], "final_risk_score": rl["final_risk_score"],
            "score_path": {"raw_anomaly_score": state["anomaly"]["raw_anomaly_score"],
                           "adjusted_score": state["context"]["adjusted_score"],
                           "final_risk_score": rl["final_risk_score"]},
            "fired_rules": [f"{r['id']}: {r['message']}" for r in rl["fired_rules"]],
            "conflicts": [c["explanation"] for c in rl["conflicts"]],
            "context_rules": [f"{c['id']} {c['name']} ×{c['factor']}" for c in state["context"]["applied_rules"]],
            "ai_reasons": state["anomaly"]["layer_reasons"],
            "recommendation": inv.get("recommendation", rl["decision"]),
            "narrative": inv.get("narrative"), "policy_references": (inv.get("policy_assessment") or {}).get("policy_references", []),
            "next_steps": (inv.get("policy_assessment") or {}).get("next_steps", []),
            "grounded": inv.get("grounded"), "plan": plan, "plan_source": plan_source, "skipped": state["skipped"],
        }


class FraudAgentSystem:
    """Agent'ları oluşturur, bus'a kaydeder ve dış dünyaya tek giriş noktası sunar."""

    def __init__(self, svc: FraudService, use_llm_planner: bool = True):
        self.svc = svc
        self.bus = MessageBus()
        for a in (OrchestratorAgent(svc, use_llm_planner), FeatureAgent(svc), ScoringAgent(svc), ContextAgent(svc),
                  RuleAgent(svc), KnowledgeAgent(svc), InvestigatorAgent(svc)):
            self.bus.register(a)

    def run(self, transaction_id: int | None = None, transaction: dict | None = None) -> dict:
        from .bus import Message
        conv = uuid.uuid4().hex[:8]
        payload = {"transaction_id": transaction_id, "transaction": transaction}
        reply = self.bus.send(Message("User", "Orchestrator", "REQUEST", "analyze_transaction", payload, conv))
        if reply.performative == "FAILURE":
            raise RuntimeError(reply.payload["error"])
        return {**reply.payload, "conversation_id": conv,
                "trace": self.bus.trace(conv).to_dict(orient="records")}
