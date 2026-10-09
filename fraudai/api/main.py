"""FastAPI servis katmanı (Adım 10).

Çalıştırma (proje kökünden):
    uvicorn fraudai.api.main:app --reload
Dokümantasyon: http://localhost:8000/docs

Endpoint'ler:
    GET    /health                 servis ve bileşen durumu
    POST   /score                  anomali skoru (+ context-adjusted skor ve risk seviyesi)
    POST   /explain                katman gerekçeleri + context kuralları + rule engine kararı (+ opsiyonel RAG)
    POST   /rules/evaluate         bir kaydı kural setine (ve/veya istekte verilen kurallara) göre değerlendirir
    GET    /rules                  aktif kural seti
    POST   /rules                  çalışma anında kural ekler/günceller
    DELETE /rules/{rule_id}        kuralı kaldırır
    POST   /rules/reload           kural dosyalarını diskten yeniden yükler
    POST   /rag/query              bilgi tabanına soru (retrieval + LLM)
    POST   /agents/investigate     multi-agent inceleme akışı
"""

from functools import lru_cache

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from .. import __version__
from ..agents import FraudAgentSystem
from ..llm import OllamaNotAvailable
from ..service import FraudService
from .schemas import (ExplainRequest, InvestigateRequest, RagQueryRequest, RuleEvaluateRequest, RuleIn,
                      ScoreRequest, ScoreResponse)


@lru_cache
def get_service() -> FraudService:
    return FraudService()


@lru_cache
def get_agents() -> FraudAgentSystem:
    return FraudAgentSystem(get_service())


def _handle(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except OllamaNotAvailable as e:  # RAG / agent'lar için local LLM gerekli
        raise HTTPException(503, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\""))
    except (ValueError, LookupError) as e:
        raise HTTPException(422, str(e))


scoring = APIRouter(tags=["scoring"])
rules = APIRouter(prefix="/rules", tags=["rules"])
rag = APIRouter(prefix="/rag", tags=["rag"])
agents = APIRouter(prefix="/agents", tags=["agents"])


@scoring.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest, svc: FraudService = Depends(get_service)):
    return _handle(svc.score, transaction_id=req.transaction_id, transaction=req.transaction,
                   update_state=req.update_state)


@scoring.post("/explain")
def explain(req: ExplainRequest, svc: FraudService = Depends(get_service)):
    return _handle(svc.explain, include_rag=req.include_rag, transaction_id=req.transaction_id,
                   transaction=req.transaction)


@rules.post("/evaluate")
def evaluate_rules(req: RuleEvaluateRequest, svc: FraudService = Depends(get_service)):
    return _handle(svc.evaluate_rules, req.record, extra_rules=req.rules,
                   conflict_resolution=req.conflict_resolution, only_extra=req.only_given_rules)


@rules.get("")
def list_rules(svc: FraudService = Depends(get_service)):
    return {"settings": svc.rules.settings, "rules": svc.rule_list()}


@rules.post("", status_code=201)
def add_rule(rule: RuleIn, svc: FraudService = Depends(get_service)):
    return _handle(svc.add_rule, rule.to_rule())


@rules.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: str, svc: FraudService = Depends(get_service)):
    _handle(svc.remove_rule, rule_id)


@rules.post("/reload")
def reload_rules(svc: FraudService = Depends(get_service)):
    return {"n_rules": _handle(svc.reload_rules)}


@rag.post("/query")
def rag_query(req: RagQueryRequest, svc: FraudService = Depends(get_service)):
    return _handle(svc.rag_query, req.question, transaction_id=req.transaction_id, k=req.k)


@agents.post("/investigate")
def investigate(req: InvestigateRequest, system: FraudAgentSystem = Depends(get_agents)):
    return _handle(system.run, transaction_id=req.transaction_id, transaction=req.transaction)


def create_app() -> FastAPI:
    app = FastAPI(title="AI Fraud & Anomaly Detection Platform", version=__version__,
                  description="Çok katmanlı anomali tespiti, context adjust, rule engine, RAG ve multi-agent inceleme.")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["system"])
    def health(svc: FraudService = Depends(get_service)):
        loaded = [k for k in ("scorer", "context", "rules", "store", "rag") if k in svc.__dict__]
        return {"status": "ok", "version": __version__, "loaded_components": loaded,
                "n_rules": len(svc.rules.rules), "n_context_rules": len(svc.context.rules)}

    for r in (scoring, rules, rag, agents):
        app.include_router(r)
    return app


app = create_app()
