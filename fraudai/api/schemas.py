
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TxRef(BaseModel):
    """Bir işlemi ya kimliğiyle (batch skorlanmış veriden) ya da ham alanlarıyla (online skorlama) tanımlar."""
    transaction_id: int | None = Field(None, description="Batch skorlanmış bir işlemin TransactionID'si")
    transaction: dict[str, Any] | None = Field(
        None, description="Ham işlem kaydı (train_transaction + train_identity alanları). "
                          "Zorunlu: TransactionDT, TransactionAmt, card1; diğer alanlar eksikse null kabul edilir.")

    @model_validator(mode="after")
    def one_of(self):
        if (self.transaction_id is None) == (self.transaction is None):
            raise ValueError("transaction_id veya transaction alanlarından tam olarak biri verilmeli")
        if self.transaction is not None:
            missing = [k for k in ("TransactionDT", "TransactionAmt", "card1") if k not in self.transaction]
            if missing:
                raise ValueError(f"transaction içinde zorunlu alanlar eksik: {missing}")
        return self


class ScoreRequest(TxRef):
    update_state: bool = Field(False, description="True ise işlem entity durumuna yazılır (akış modu)")


class ScoreResponse(BaseModel):
    transaction_id: int | None
    source: Literal["batch", "online"]
    raw_anomaly_score: float
    layer_scores: dict[str, float]
    dominant_layer: str
    context_factor: float
    adjusted_score: float
    risk_level: Literal["low", "medium", "high"]
    applied_context_rules: list[str]


class ExplainRequest(TxRef):
    include_rag: bool = Field(False, description="True ise politika dokümanlarıyla RAG değerlendirmesi eklenir")


class RuleEvaluateRequest(BaseModel):
    record: dict[str, Any] = Field(..., description="Değerlendirilecek kayıt (feature ve skor alanları)")
    rules: list[dict[str, Any]] | None = Field(None, description="Bu istek için geçici olarak eklenecek kurallar")
    only_given_rules: bool = Field(False, description="True ise yalnızca `rules` içindeki kurallar çalışır")
    conflict_resolution: Literal["priority", "severity"] | None = None


class RuleIn(BaseModel):
    id: str
    name: str
    priority: int = 100
    enabled: bool = True
    tags: list[str] = []
    if_: dict[str, Any] = Field(..., alias="if")
    then: dict[str, Any]

    def to_rule(self) -> dict:
        d = self.model_dump(by_alias=True)
        return d


class RagQueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    transaction_id: int | None = Field(None, description="Verilirse işlemin açıklaması bağlama eklenir")
    k: int | None = Field(None, ge=1, le=10)


class InvestigateRequest(TxRef):
    pass
