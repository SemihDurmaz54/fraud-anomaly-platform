# AI Destekli Fraud & Anomali Tespit Platformu

IEEE-CIS Fraud Detection verisi üzerinde uçtan uca bir prototip: çok katmanlı anomali tespiti, context-aware skor düzeltme, konfigüre edilebilir rule engine, RAG, multi-agent orkestrasyon ve FastAPI servisi.

## Klasör yapısı

```
fraud-anomaly-platform/
├── fraud_case.ipynb          # Adım 1–10: tüm veri işlemleri, değerlendirmeler ve çıkarımlar
├── docs/TEKNIK_DOKUMAN.md    # Context kuralları, rule set, öncelikler ve etkileri (teknik doküman)
├── config/ 
│   ├── settings.yaml         # yollar, LLM/embedding ayarları, risk eşikleri
│   ├── context_rules.yaml    # Adım 6: context adjust kuralları
│   └── rules.yaml            # Adım 7: iş kuralları
├── data/
│   └── raw/                  # train_transaction.csv, train_identity.csv (Kaggle'dan indirilir, repoya eklenmez)
├── knowledge_base/           # Adım 8: kurgusal politika dokümanları (RAG)
├── artifacts/                # notebook çıktıları (modeller, entity durumu, skorlar, RAG indeksi)
├── fraudai/                  # yeniden kullanılabilir paket
│   ├── conditions.py         # ortak JSON/YAML koşul dili
│   ├── context_engine.py     # Adım 6
│   ├── rule_engine.py        # Adım 7
│   ├── scoring.py            # online (tek işlem) skorlama
│   ├── llm.py                # Ollama (local LLM) istemcisi
│   ├── rag/                  # Adım 8: kb.py, embeddings.py, store.py, pipeline.py
│   ├── agents/               # Adım 9: bus.py, base.py, agents.py
│   ├── service.py            # bileşenleri birleştiren servis katmanı
│   └── api/                  # Adım 10: main.py, schemas.py
├── test_platform.py          # LLM, RAG ve agent akışının uçtan uca hızlı testi
└── requirements.txt
```

## Kurulum

```bash
git clone https://github.com/SemihDurmaz54/fraud-anomaly-platform.git
cd fraud-anomaly-platform
pip install -r requirements.txt
```

Veri: `train_transaction.csv` ve `train_identity.csv` dosyalarını `data/raw/` altına koyun (veya notebook'taki `DATA_DIR` değişkenini değiştirin).

## 1) Notebook

`fraud_case.ipynb` dosyasını proje kökünden açıp baştan sona çalıştırın. Notebook, API'nin ihtiyaç duyduğu çıktı dosyalarını `artifacts/` altına yazar:

* `scoring_bundle.joblib`
* `entity_state.joblib`
* `tx_context.parquet`
* `rag_index/`

## 2) Local LLM (Ollama)

RAG ve agent'lar local LLM ile çalışacak şekilde tasarlandı:

```bash
# https://ollama.com adresinden Ollama'yı kurun, sonra:
ollama pull qwen2.5:3b     # LLM (cevap üretimi, reasoning, planlama)
ollama pull bge-m3         # çok dilli embedding modeli
```

Model adları `config/settings.yaml` dosyasından veya `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL` ve `OLLAMA_HOST` ortam değişkenleriyle değiştirilebilir.

RAG, agent'lar ve ilgili API endpoint'leri (`/explain` ile `include_rag`, `/rag/query`, `/agents/investigate`) Ollama'nın çalışıyor olmasını gerektirir. **Ollama'ya ulaşılamazsa veya model yüklü değilse** sistem, kurulum adımlarını içeren açık bir hata verir. Skorlama, context ve rule engine Ollama olmadan da çalışır.

## 3) API

```bash
uvicorn fraudai.api.main:app --reload
# Swagger arayüzü: http://localhost:8000/docs
```

| Endpoint | Metot | Açıklama |
|---|---|---|
| `/score` | POST | Anomali skoru ve context-adjusted skor |
| `/explain` | POST | Katman gerekçeleri, context kuralları, kural kararı; `include_rag` ile politika değerlendirmesi |
| `/rules/evaluate` | POST | Kayıt için kural değerlendirmesi; istekte geçici kural ve çatışma stratejisi verilebilir |
| `/rules` | GET / POST / DELETE | Kuralları listeleme, ekleme, silme |
| `/rules/reload` | POST | YAML dosyalarını yeniden yükleme |
| `/rag/query` | POST | Bilgi tabanına soru |
| `/agents/investigate` | POST | Multi-agent inceleme akışı |
| `/health` | GET | Servis durumu |

Örnekler:

```bash
curl -X POST localhost:8000/score -H "Content-Type: application/json" -d '{"transaction_id": 3435656}'

curl -X POST localhost:8000/explain -H "Content-Type: application/json" \
     -d '{"transaction_id": 3435656, "include_rag": true}'

curl -X POST localhost:8000/rag/query -H "Content-Type: application/json" \
     -d '{"question": "Card testing şüphesinde ne yapılır?"}'
```

Ham bir işlem `{"transaction": {...}}` ile gönderilebilir. Zorunlu alanlar: `TransactionDT`, `TransactionAmt`, `card1`. Diğer alanlar eksikse boş kabul edilir. En doğru sonuç için tüm ham alanlar gönderilmelidir.

## 4) Test

Notebook çalıştırılıp çıktı dosyaları üretildikten ve Ollama modelleri indirildikten sonra proje kökünden:

```bash
python test_platform.py
```

Betik sırasıyla şunları kontrol eder:

1. LLM ve embedding bağlantısı
2. Bilgi tabanına örnek RAG soruları (bilgi tabanında olmayan bir soru için "bulunamadı" cevabı beklenir)
3. Örnek bir işlem (TransactionID 3435656) için açıklama ve RAG tabanlı politika değerlendirmesi
4. Multi-agent inceleme akışı ve agent'lar arası mesaj izi

## Tasarım desenleri

| Desen | Nerede | Ne yapıyor |
|---|---|---|
| Facade | `service.py` → `FraudService` | Skorlama, context, kural motoru ve RAG'i tek arayüzde topluyor; API ve agent'lar yalnızca bu sınıfı kullanıyor |
| Strategy | `rule_engine.py` → `conflict_resolution` | Çatışma çözüm yöntemi (priority / severity) konfigürasyondan seçiliyor |
| Interpreter + Composite | `conditions.py` | JSON/YAML koşul dili; `all` / `any` / `not` ile iç içe koşul ağacı kurulup yorumlanıyor |
| Mediator | `agents/bus.py` → `MessageBus` | Agent'lar birbirleriyle doğrudan değil, bus üzerinden mesajlaşıyor |
| Registry | `MessageBus.registry` | Görev → agent eşlemesi; orkestratör görevi yapacak agent'ı bilmeden devrediyor |
| Template Method | `agents/base.py` → `Agent` | Mesaj alma ve hata yönetimi temel sınıfta; alt sınıflar yalnızca kendi görevlerini tanımlıyor |
| Command | `agents/bus.py` → `Message` | Her istek gönderen, alıcı, görev ve veriyi taşıyan bir nesne; log'lanıp izlenebiliyor |
| Factory | `get_llm`, `get_embedder`, `RuleEngine.from_file`, `ContextEngine.from_yaml`, `create_app` | Nesne oluşturma mantığı tek bir yerde |
| Adapter | `llm.py`, `rag/embeddings.py` | Ollama HTTP API'sini sistemin `generate()` / `encode()` arayüzüne uyarlıyor |
| Dependency Injection | `api/main.py` → `Depends(get_service)`; `RAGPipeline(embedder, llm)` | Bağımlılıklar dışarıdan veriliyor; testte kolayca değiştirilebiliyor |
| Singleton + Lazy Loading | `@lru_cache get_service`, `@cached_property` | Servis tek örnek; modeller ve dosyalar ilk kullanımda yükleniyor |
| Pipeline | `rag/pipeline.py`, orkestratör akışı | RAG: sinyal → sorgu → retrieval → context injection → LLM → doğrulama |
