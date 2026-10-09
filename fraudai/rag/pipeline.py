"""RAG pipeline (Adım 8): chunking → embedding → vector search → LLM context injection → reasoning.

İki kullanım:
* ``answer(question)``: bilgi tabanına serbest soru (ör. "card testing politikası nedir?").
* ``reason_transaction(explanation)``: bir işlemin skor/kural açıklamasını politika dokümanlarıyla
  ilişkilendirip yapılandırılmış bir değerlendirme üretir (RAG tabanlı reasoning akışı):

    1. Sinyal çıkarımı  : tetiklenen kurallar, context kuralları, AI katman gerekçeleri
    2. Sorgu üretimi    : her sinyal için bir retrieval sorgusu
    3. Retrieval        : hibrit arama (dense benzerlik + kural kimliği eşleşmesi), tekilleştirme
    4. Context injection: kaynaklar numaralı olarak prompt'a eklenir
    5. LLM reasoning    : JSON formatında öneri, gerekçe, politika referansları, sonraki adımlar
    6. Doğrulama        : LLM'in atıf yaptığı politika kimlikleri gerçekten getirilen kaynaklarda var mı?
"""
from __future__ import annotations

from pathlib import Path

from ..llm import get_llm, parse_json
from .embeddings import get_embedder
from .kb import RULE_ID, build_chunks
from .store import VectorStore

SYSTEM_QA = ("Sen bir ödeme şirketinin fraud analisti asistanısın. Yalnızca BAĞLAM bölümündeki bilgileri kullan. "
             "Kuralları birbirine karıştırma: her kuralın koşulunu ve sonucunu ayrı ayrı, metindeki gibi aktar "
             "(ör. 'şüphe' ile 'doğrulanmış' durumlar farklıdır). Her cümlenin sonunda [n] biçiminde kaynak numarası "
             "ve varsa kural kimliğini (KB-xxx) belirt. Bağlamda bilgi yoksa "
             "'Bilgi tabanında bu konuda politika bulunamadı.' de. Türkçe, kısa ve madde madde cevap ver.")

SYSTEM_TX = ("Sen bir fraud inceleme uzmanısın. Sana bir işlemin anomali skoru, tetiklenen kurallar ve ilgili "
             "politika dokümanları veriliyor. Yalnızca verilen politikalara dayanarak karar önerisi üret. "
             "Politika kimliği uydurma; yalnızca BAĞLAM'da geçen KB-xxx kimliklerini kullan. "
             "Çıktıyı yalnızca şu JSON şemasıyla ver: {\"recommendation\": \"APPROVE|REVIEW|BLOCK\", "
             "\"risk_summary\": str, \"policy_references\": [str], \"rationale\": [str], "
             "\"next_steps\": [str], \"citations\": [str]}")

class RAGPipeline:
    def __init__(self, kb_dir: str | Path, embedder=None, llm=None, k: int = 4, index_dir: str | Path | None = None):
        """embedder / llm verilmezse varsayılan Ollama modelleri kullanılır (Ollama yoksa talimatlı hata)."""
        self.kb_dir = Path(kb_dir)
        self.embedder = embedder or get_embedder()
        self.llm = llm or get_llm()
        self.k = k
        self.index_dir = Path(index_dir) if index_dir else None
        self.store = VectorStore()
        self.chunks: list[dict] = []

    # ------------------------------------------------------------------ indeksleme
    def build_index(self) -> "RAGPipeline":
        self.chunks = build_chunks(self.kb_dir)
        texts = [c["text"] for c in self.chunks]
        self.embedder.fit(texts)
        self.store = VectorStore()
        self.store.add(self.chunks, self.embedder.encode(texts))
        if self.index_dir:
            self.store.save(self.index_dir)
        return self

    # ------------------------------------------------------------------ retrieval
    def retrieve(self, query: str, k: int | None = None, rule_boost: float = 0.15) -> list[dict]:
        """Hibrit arama: kosinüs benzerliği + sorguda geçen kural kimliği chunk'ta da geçiyorsa bonus."""
        k = k or self.k
        q = self.embedder.encode([query])[0]
        cands = self.store.search(q, k=min(len(self.store), k * 4))
        qids = set(RULE_ID.findall(query))
        for c in cands:
            c["dense_score"] = c["score"]
            c["score"] = c["score"] + rule_boost * len(qids & set(c["rule_ids"]))
        return sorted(cands, key=lambda c: -c["score"])[:k]

    @staticmethod
    def format_context(sources: list[dict]) -> str:
        return "\n\n".join(f"[{i}] ({s['title']} › {s['section']})\n{s['text'].split(chr(10), 1)[-1]}"
                           for i, s in enumerate(sources, 1))

    # ------------------------------------------------------------------ serbest soru
    def answer(self, question: str, k: int | None = None, transaction: dict | None = None,
               min_score: float | None = None, retrieval_query: str | None = None) -> dict:
        # alakasız sorularda bağlama gürültü eklememek için benzerlik eşiği
        min_score = self.embedder.min_score if min_score is None else min_score
        sources = [s for s in self.retrieve(retrieval_query or question, k) if s["score"] >= min_score]
        tx_block = f"\n\nİŞLEM BİLGİSİ:\n{transaction}" if transaction else ""
        prompt = f"BAĞLAM:\n{self.format_context(sources)}{tx_block}\n\nSORU: {question}\nCEVAP:"
        text = self.llm.generate(prompt, system=SYSTEM_QA)
        return {"question": question, "answer": text, "llm": self.llm.name, "embedder": self.embedder.name,
                "sources": [_src(s, i) for i, s in enumerate(sources, 1)], "prompt": prompt}

    # ------------------------------------------------------------------ işlem bazlı reasoning
    def build_queries(self, ex: dict) -> list[str]:
        qs = []
        for r in ex.get("fired_rules", []):
            qs.append(f"{r['id']} {r['name']} {' '.join(r.get('tags', []))} politikası")
        for c in ex.get("context_rules", []):
            qs.append(f"{c['id']} {c['name']} {c.get('category', '')}")
        for layer, reason in (ex.get("ai_layer_reasons") or {}).items():
            if reason and reason != "—":
                qs.append(f"{layer} anomali {reason.split('=')[0]}")
        qs.append(f"{ex.get('decision', 'REVIEW')} kararı inceleme ve eskalasyon prosedürü")
        return list(dict.fromkeys(qs))

    def reason_transaction(self, ex: dict, per_query_k: int = 2, max_sources: int = 6) -> dict:
        steps = []
        queries = self.build_queries(ex)
        steps.append({"step": "1-2 sinyal çıkarımı ve sorgu üretimi", "queries": queries})
        pool: dict[str, dict] = {}
        for q in queries:
            for s in self.retrieve(q, per_query_k):
                if s["chunk_id"] not in pool or s["score"] > pool[s["chunk_id"]]["score"]:
                    pool[s["chunk_id"]] = {**s, "query": q}
        sources = sorted(pool.values(), key=lambda s: -s["score"])[:max_sources]
        steps.append({"step": "3 retrieval", "n_candidates": len(pool),
                      "selected": [s["chunk_id"] for s in sources]})
        facts = {
            "decision": ex.get("decision"), "decided_by": ex.get("decided_by"),
            "final_risk_score": ex.get("final_risk_score"), "raw_anomaly_score": ex.get("raw_anomaly_score"),
            "adjusted_score": ex.get("adjusted_score"),
            "fired_rules": [f"{r['id']} {r['name']}: {r['message']}" for r in ex.get("fired_rules", [])],
            "context_rules": [f"{c['id']} {c['name']} (×{c['factor']})" for c in ex.get("context_rules", [])],
            "ai_layer_reasons": ex.get("ai_layer_reasons", {}),
        }
        prompt = (f"BAĞLAM (politika dokümanları):\n{self.format_context(sources)}\n\n"
                  f"İŞLEM ANALİZİ:\n{facts}\n\n"
                  "GÖREV: Bu işlem için politikalara dayalı bir karar önerisi üret. Yalnızca JSON döndür.")
        steps.append({"step": "4 context injection", "prompt_chars": len(prompt), "n_sources": len(sources)})
        raw = self.llm.generate(prompt, system=SYSTEM_TX, json_mode=True)
        out = parse_json(raw)
        steps.append({"step": "5 LLM reasoning", "llm": self.llm.name})
        available_ids = set(RULE_ID.findall(" ".join(s["text"] for s in sources)))
        cited = set(out.get("policy_references", []) or [])
        hallucinated = sorted(i for i in cited if i not in available_ids)
        steps.append({"step": "6 doğrulama", "cited_policies": sorted(cited),
                      "unsupported_citations": hallucinated, "grounded": not hallucinated})
        return {"assessment": out, "sources": [_src(s, i) for i, s in enumerate(sources, 1)],
                "reasoning_steps": steps, "prompt": prompt, "llm": self.llm.name, "embedder": self.embedder.name}


def _src(s: dict, i: int) -> dict:
    return {"ref": f"[{i}]", "chunk_id": s["chunk_id"], "doc_id": s["doc_id"], "title": s["title"],
            "section": s["section"], "score": round(s["score"], 4), "rule_ids": s["rule_ids"],
            "preview": s["text"].split("\n", 1)[-1][:220]}
