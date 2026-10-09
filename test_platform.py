"""Platformun hızlı testi: LLM bağlantısı, RAG, işlem bazlı RAG değerlendirmesi ve agent akışı.

Proje kök klasöründe çalıştırın:
    python test_platform.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows konsolunda Türkçe karakterler için

from fraudai.agents import FraudAgentSystem
from fraudai.service import FraudService

TX_ID = 3435656  # gece + yeni cihaz → BLOCK örneği


def title(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


svc = FraudService()

title("1) LLM ve embedding bağlantısı")
rag = svc.rag
print("LLM      :", rag.llm.name)
print("Embedding:", rag.embedder.name)

title("2) RAG: bilgi tabanına sorular")
for q in ["Card testing şüphesinde ne yapılır?",
          "KB-217 deneme kuralı ne diyor?",
          "Güvenilir müşteri beyaz listesi BLOCK kararını geçersiz kılabilir mi?",
          "Kripto para transferlerinde limit nedir?"]:   # bilgi tabanında yok → "bulunamadı" beklenir
    r = rag.answer(q)
    print(f"\nSORU: {q}\nCEVAP: {r['answer']}\nKAYNAKLAR: {[s['chunk_id'] for s in r['sources']]}")

title(f"3) İşlem bazlı açıklama + RAG değerlendirmesi (TransactionID {TX_ID})")
ex = svc.explain(transaction_id=TX_ID, include_rag=True)
print(ex["summary"])
print(json.dumps(ex["rag"]["assessment"], ensure_ascii=False, indent=2))
print("Atıflar kaynaklarda var mı (grounded):", ex["rag"]["reasoning_steps"][-1]["grounded"])

title("4) Multi-agent inceleme")
res = FraudAgentSystem(svc).run(transaction_id=TX_ID)
print("Karar:", res["decision"], "| Öneri:", res["recommendation"], "| Plan:", res["plan"], f"({res['plan_source']})")
print("\nAnaliz notu:\n", res["narrative"])
print("\nMesaj akışı:")
for m in res["trace"]:
    print(f"  {m['akış']:45s} {m['performative']:9s} {m['görev']}")
