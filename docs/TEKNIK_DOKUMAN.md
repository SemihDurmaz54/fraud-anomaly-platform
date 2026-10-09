# Teknik Doküman: Context Adjust, Rule Engine, RAG, Agentic AI ve API

Bu doküman, case çalışmasının 6–10. adımlarında tasarlanan bileşenlerin **mantığını, kurallarını, önceliklerini ve anomali tespiti üzerindeki etkilerini** açıklar. Sayısal sonuçlar `fraud_case.ipynb` notebook'unun 6–10. bölümlerinden alınmıştır.

**Değerlendirme kurgusu:**

* **Kalibrasyon dönemi:** ilk 120 gün, 410.601 işlem. Çarpanlar ve eşikler yalnızca bu dönemde belirlendi.
* **Test dönemi:** son 62 gün, 179.939 işlem. Tüm etkiler bu dönemde ölçüldü.
* **Alarm:** en yüksek skorlu %2'lik dilim (eşit alarm bütçesi) ya da kalibrasyon döneminde belirlenen sabit eşik.
* **Etiket kullanımı:** `isFraud` etiketi kurallar çalışırken kullanılmaz. Yalnızca kalibrasyonda ve ölçümde kullanılır.

---

## 1. Genel mimari

```
ham işlem ─► Feature (Adım 3) ─► 4 katmanlı anomali skoru (Adım 4) ─► raw_anomaly_score (Adım 5)
                                                                          │
                       config/context_rules.yaml ─► Context Adjust (Adım 6) ─► adjusted_score
                                                                          │
                              config/rules.yaml ─► Rule Engine (Adım 7) ─► karar + final_risk_score + açıklama
                                                                          │
                          knowledge_base/*.md ─► RAG (Adım 8) ─► politika bazlı değerlendirme
                                                                          │
                     Agent'lar (Adım 9) bu adımları orkestre eder; API (Adım 10) dış dünyaya açar
```

Context ve rule engine **aynı koşul dilini** kullanır (`fraudai/conditions.py`).

* Bir koşul ya bir karşılaştırmadır ya da bunları gruplayan mantıksal bir yapıdır: `all` (VE), `any` (VEYA), `not` (DEĞİL).
* Desteklenen operatörler: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `not_in`, `is_null`, `not_null`, `contains`. Değer yerine başka bir alan da verilebilir (`value_field`).
* `eval` kullanılmaz; yalnızca tanımlı operatörler çalışır. Hatalı bir koşul yüklenirken reddedilir.
* Aynı koşul hem tek kayıt hem de tüm veri üzerinde vektörize olarak çalışır. 590 bin işlem yaklaşık 1–2 saniyede değerlendirilir.

---

## 2. Context Adjust Engine (Adım 6)

### 2.1 Amaç

Adım 5'teki skor **istatistiksel** nadirliği ölçer. Ancak bazı nadir durumlar iş açısından olağandır: yerleşik bir müşterinin büyük alışverişi, sık alışveriş yapan bir kullanıcının yüksek işlem sıklığı veya hafta sonu perakende yoğunluğu gibi. Context engine skoru iş ve zaman bağlamına göre yeniden ağırlıklandırarak **false positive sayısını azaltır**.

### 2.2 Formül ve birleştirme

```
adjusted_score = clip(raw_anomaly_score × Π factorᵢ , 0, 100)
Π factorᵢ  ∈ [0,5 ; 1,5]
```

* Birden fazla kural aynı işleme uygulanabilir. Çarpanlar **çarpılır** ve toplam çarpan sınırlanır. Böylece bağlam AI skorunu düzeltir ama tamamen geçersiz kılamaz.
* Çarpımsal yapı seçildi çünkü bağlam, skoru **göreli** olarak etkilemeli. Güvenilir bir kullanıcıda 95 puanlık bir anomali 71'e iner, 40 puanlık bir anomali 30'a iner; sıralama korunur.

### 2.3 Yerel saat

`TransactionDT` göreli saniyedir ve saat dilimi bilinmez. Bu yüzden saat, işlem hacminden yeniden konumlandırıldı:

* Hacmin en düşük olduğu ham saat (09:00) yerel **04:00** kabul edildi; ofset 5 saat.
* Bu ofsetle yerel 00–05 arasının fraud oranı %7,8. Bu, ortalamanın (%3,5) iki katından fazla ve gece saatleriyle tutarlı.

### 2.4 Türetilmiş bağlam alanları

Bu alanlar YAML'da koşul olarak tanımlıdır ve kod değiştirmeden güncellenebilir.

| Alan | Tanım |
|---|---|
| `is_business_hours` | Yerel 09–18 ve hafta içi |
| `is_off_hours` | Yerel 00–05 |
| `is_trusted_entity` | ≥ 5 geçmiş işlem, ≥ 30 gün geçmiş, yeni cihaz/e-posta yok, tutar kendi ortalamasının 1/3–3 katı aralığında |
| `is_frequent_entity` | ≥ 10 geçmiş işlem, ≥ 30 gün geçmiş, yeni cihaz yok |
| `is_high_value_customer` | (Tutar > 500 ve kullanıcı bilinen biri) veya (geçmiş ortalama ≥ 300, tutar ≤ 2 × ortalama, ≥ 3 geçmiş işlem) |

Tüm entity alanları **yalnızca geçmiş işlemlerden** hesaplanır; gelecekten bilgi sızmaz.

### 2.5 Kural seti

Alarm isabeti, kalibrasyon döneminde ham skoru en yüksek %2'de olan işlemler içindeki fraud oranıdır. Genel ortalama **%16,7**.

| ID | Kategori | Kural | Çarpan | Durum | Segmentin alarm isabeti | Gerekçe |
|---|---|---|---|---|---|---|
| CTX-01 | Business hours | Mesai saati (hafta içi 09–18) | 0,95 | aktif | %13,6 (diğer saatler %18,8) | Yoğun ve izlenen saatlerde sapmaların çoğu meşru. 0,85 çarpanı ablasyonda isabeti düşürdüğü için etki küçük tutuldu |
| CTX-02 | Business hours | Mesai dışı / gece (00–05) | 1,15 | aktif | %25,8 | İşlemlerin %5'i ama fraud oranı %7,8 |
| CTX-03 | Weekend | Hafta sonu ve W/R ürünü | 0,90 | aktif | %8,8 | Hafta sonu perakende hacmi doğal olarak artıyor |
| CTX-04 | Weekend | Hafta sonu yeni cihaz | 1,10 | **kapalı** | %22,6 | Ablasyonda isabeti düşürdü; sinyal R007 ile kural motorunda |
| CTX-05 | Trusted entity | Güvenilir kullanıcı | 0,75 | aktif | %10,7 (diğerleri %17,0) | Tutarlı geçmişi olan kullanıcıda sapmalar çoğunlukla meşru |
| CTX-06 | Trusted entity | Sık işlem yapan yerleşik entity | 0,85 | aktif | %12,8 | Yüksek işlem sıklığı bu kullanıcı için normal |
| CTX-07 | Yüksek değerli müşteri | Bilinen müşterinin yüksek tutarı | 0,80 | aktif | **%3,6** | Tutar tek başına risk değil |
| CTX-08 | İşlem tipi profili | R ürünü | 0,85 | aktif | %6,0 | Düşük riskli ürün |
| CTX-09 | İşlem tipi profili | W ürünü | 0,90 | aktif | %7,3 | Fraud oranı %2,1 |
| CTX-10 | İşlem tipi profili | C ürünü | 1,05 | **kapalı** | %22,7 | C zaten alarmların %56'sı; artırmak isabeti düşürdü |
| CTX-11 | Coğrafi risk | Fatura adresi yok | 1,05 | aktif | %22,4 (diğerleri %9,8) | Coğrafi doğrulama yapılamıyor |
| CTX-12 | Account takeover | Yerleşik kullanıcıda yeni cihaz | 1,10 | **kapalı** | %20,2 | Ablasyonda isabeti düşürdü; sinyal R007 ile kural motorunda |

### 2.6 Kalibrasyon yöntemi

Çarpanlar iki aşamada belirlendi; iki aşamada da yalnızca kalibrasyon dönemi kullanıldı.

1. **Segment analizi (hipotez):** Segmentin alarm isabeti ortalamanın altındaysa false positive yoğundur ve çarpan < 1 olmalıdır; üstündeyse çarpan > 1 olmaya adaydır.
2. **Ablasyon (doğrulama):** Her kural tek tek açılıp kapatılarak %2 bütçedeki alarm isabetine etkisi ölçüldü.

**Önemli gözlem:** Skor artıran kuralların çoğu, segment isabetleri yüksek olduğu hâlde toplam isabeti **düşürdü**. Nedeni, ham skorun bu riskli segmentleri zaten listenin tepesine yerleştirmiş olmasıdır. Artırıcı çarpan bu segmentteki *düşük* skorlu işlemleri listeye taşıyarak gerçekten riskli işlemlerin yerini alıyor. Bu yüzden bağlamın asıl değeri **false positive'leri bastırmasında**.

### 2.7 False positive üzerindeki etki (test dönemi)

| Ölçüt | Ham skor | Context-adjusted | Değişim |
|---|---|---|---|
| Eşit bütçe (%2): false positive | 3.119 | 2.718 | **−%12,9** |
| Eşit bütçe (%2): yakalanan fraud | 479 | 880 | **+%84** |
| Eşit bütçe (%2): alarm isabeti | %13,3 | %24,5 | +11,2 puan |
| Sabit eşik (92,7): false positive | 3.124 | 2.387 | **−%23,6** |
| Sabit eşik (92,7): yakalanan fraud | 480 | 810 | +%69 |
| ROC-AUC | 0,753 | 0,76 | |

* Alarm listesinden çıkarılan 2.259 işlemin fraud oranı %3,9; yerlerine giren işlemlerinki %21,8.
* Çıkarılanlarda en sık uygulanan kurallar: CTX-06 (sık işlem yapan entity), CTX-05 (güvenilir kullanıcı) ve CTX-01 (mesai saati).
* Tipik bir false positive: 400'den fazla geçmiş işlemi olan, hep aynı tutarı ödeyen bir kullanıcının işlemi. Ham skoru 99, context sonrası 63.

---

## 3. Rule Engine (Adım 7)

### 3.1 Kural şeması

```yaml
- id: R003
  name: Card testing (küçük tutarlı ardışık denemeler)
  priority: 15                     # küçük sayı = yüksek öncelik
  enabled: true
  tags: [card_testing, velocity]
  if:                              # koşul ağacı (all / any / not + karşılaştırmalar)
    all:
      - {field: TransactionAmt, op: lt, value: 10}
      - {field: uid_tx_last_1h, op: gte, value: 3}
  then:
    action: REVIEW                 # BLOCK | REVIEW | FLAG | ALLOW
    score_delta: 15                # final_risk_score'a katkı
    reason: "{TransactionAmt:.2f} USD'lik küçük işlem; son 1 saatte {uid_tx_last_1h} işlem"
```

* Kurallar YAML veya JSON dosyasından yüklenir.
* Çalışma anında `add_rule`, `remove_rule` ve `set_enabled` ile değiştirilebilir. API karşılıkları: `POST /rules`, `DELETE /rules/{id}`, `POST /rules/reload`.
* Yüklenirken doğrulanır; bilinmeyen operatör veya aksiyon reddedilir.

### 3.2 Aksiyonlar

| Aksiyon | Ciddiyet | Karar verir mi? | Anlamı |
|---|---|---|---|
| BLOCK | 4 | Evet | İşlemi reddet |
| REVIEW | 3 | Evet | Manuel inceleme kuyruğuna al |
| FLAG | 2 | Hayır | Yalnızca skoru ayarlar ve gerekçeye not düşer |
| ALLOW | 1 | Evet | Beyaz liste: otomatik onay |

### 3.3 Karar algoritması

1. Aktif kurallar öncelik sırasıyla değerlendirilir. Eşit öncelikte ciddiyeti yüksek olan önce gelir.
2. `final_risk_score = clip(adjusted_score + clip(Σ score_delta, −30, +30), 0, 100)`. Kuralların toplam etkisi ±30 ile sınırlıdır.
3. Karar veren aksiyonlar (BLOCK, REVIEW, ALLOW) arasındaki çatışma `conflict_resolution` ayarıyla çözülür:
   * `priority` (varsayılan): öncelik numarası en küçük olan kural kazanır.
   * `severity`: en ciddi aksiyon kazanır.
4. Hiçbir karar kuralı tetiklenmezse karar **AI'a** kalır: `final_risk_score ≥ 95 → REVIEW`, aksi hâlde APPROVE.
5. Geçersiz kılınan kurallar `conflicts` listesinde, gerekçesiyle birlikte raporlanır.

**Tasarım ilkesi:** AI skoru tek başına BLOCK kararı veremez. BLOCK yalnızca açıkça tanımlanmış bir kuralla verilir (KB-802).

### 3.4 Kural seti ve etkileri (test dönemi)

| Öncelik | ID | Kural | IF | THEN | Δ skor | Tetiklenme | İsabet |
|---|---|---|---|---|---|---|---|
| 1 | R001 | Gece + yüksek tutar + doğrulanamayan cihaz/adres | tutar > 200 ve gece ve (yeni cihaz veya adres yok) | BLOCK | +25 | 7 işlem | %42,9 |
| 5 | R013 | Güvenilir müşteri beyaz listesi | güvenilir ve adjusted < 80 ve son 1 saatte < 5 işlem | ALLOW | −10 | %23,8 | %1,95 (fraud oranı) |
| 10 | R007 | Gece yeni cihaz (ATO) | yeni cihaz ve gece | REVIEW | +15 | %0,26 | %22,3 |
| 12 | R006 | Yeni kullanıcıdan çok yüksek tutar | tutar > 2000 ve geçmiş işlem yok | FLAG | +5 | %0,19 | %1,4 |
| 15 | R003 | Card testing | tutar < 10 ve son 1 saatte ≥ 3 işlem | REVIEW | +15 | %0,12 | %11,9 |
| 20 | R002 | Yeni hesapta velocity burst | son 1 saatte ≥ 5 işlem ve hesap < 1 gün | REVIEW | +10 | %0,27 | %6,7 |
| 30 | R004 | Kullanıcıya göre tutar sıçraması | tutar ≥ 5 × ortalama ve ≥ 3 geçmiş işlem | FLAG | +5 | %0,36 | %5,1 |
| 35 | R005 | Yeni kartla yüksek tutar | kart ≤ 1 gün ve tutar ≥ 500 ve online kimlik var | REVIEW | +10 | %0,12 | %24,3 |
| 50 | R012 | AI yüksek risk | adjusted ≥ 95 | REVIEW | 0 | %1,21 | %26,9 |
| 60 | R008 | Çoklu cihaz | ≥ 5 cihaz | FLAG | +3 | %4,1 | %8,3 |
| 61 | R009 | Çoklu e-posta | ≥ 3 e-posta alan adı | FLAG | +3 | %8,7 | %5,6 |
| 62 | R010 | E-posta uyumsuzluğu | ödeyen ≠ alıcı e-posta | FLAG | +2 | %2,8 | %3,6 |
| 63 | R011 | Coğrafi doğrulama yok | addr1 ve dist1 boş | FLAG | +3 | %10,3 | %13,2 |

**Önceliklerin mantığı:**

* **R001 (1):** Kesin engelleme kuralları en üstte; hiçbir beyaz liste onları geçersiz kılamaz.
* **R013 (5):** Beyaz liste, REVIEW kurallarından önce gelir. Böylece güvenilir müşteriler gereksiz yere incelemeye düşmez. Ancak koşulunda `adjusted_score < 80` olduğu için yüksek anomali gösteren güvenilir müşteri yine de incelemeye gider.
* **REVIEW kuralları (10–50):** Davranış kuralları (ATO, card testing, velocity, yeni kart) AI kuralından (R012) önce gelir. Böylece kararı okunabilir bir iş kuralı verir.
* **FLAG kuralları (60+):** Karar vermez; yalnızca skoru ve gerekçeyi zenginleştirir.

**Toplam etki (test dönemi):**

| Yaklaşım | Alarm | Yakalanan fraud | False positive | İsabet |
|---|---|---|---|---|
| Rule engine + AI (REVIEW/BLOCK) | 5.231 | 1.080 | 4.151 | %20,6 |
| Yalnız ham AI skoru (aynı alarm sayısı) | 5.231 | 718 | 4.513 | %13,7 |
| Yalnız context-adjusted skor (aynı alarm sayısı) | 5.231 | 1.162 | 4.069 | %22,2 |

Kurallar ham AI'a göre false positive'leri %8 azaltıyor. Context-adjusted sıralamadan biraz daha düşük isabet veriyorlar; çünkü kuralların görevi sıralamayı iyileştirmek değil, **deterministik, denetlenebilir ve politikaya bağlı** kararlar üretmek.

### 3.5 Çatışma çözümü örneği

Aynı işlemde R013 (ALLOW, öncelik 5) ve R003 (REVIEW, öncelik 15) birlikte tetikleniyor:

* `priority` stratejisi → **APPROVE**. Gerekçe: "R003 (REVIEW, öncelik 15) → R013 (ALLOW, öncelik 5) tarafından geçersiz kılındı".
* `severity` stratejisi → **REVIEW**. Gerekçe: "R013 (ALLOW) → R003 (REVIEW) tarafından geçersiz kılındı".

Hangi stratejinin seçileceği bir risk iştahı kararıdır ve konfigürasyondan değiştirilebilir. API'de istek bazında da seçilebilir: `/rules/evaluate` → `conflict_resolution`.

### 3.6 Explainability çıktısı

Her değerlendirme şu alanları döndürür:

* `decision`, `decided_by`, `rationale`
* `base_score`, `rule_score_delta`, `final_risk_score`
* `fired_rules`: her kural için şablonla doldurulmuş **mesaj**, okunabilir **koşul**, **kanıt alanları ve değerleri**, öncelik, aksiyon, etiketler
* `conflicts`: geçersiz kılınan kurallar ve nedeni
* `ai_layer_reasons`: dört anomali katmanının gerekçeleri

`/explain` endpoint'i bunlara context kurallarının gerekçelerini ve isteğe bağlı RAG değerlendirmesini ekler.

---

## 4. RAG Pipeline (Adım 8)

| Aşama | Uygulama |
|---|---|
| Bilgi tabanı | 8 **kurgusal** politika dokümanı (`knowledge_base/`). KB-xxx maddeleri; bazıları kural motoruna bağlı (ör. KB-302 ↔ R001). Bazıları yalnızca RAG'i test etmek için eklenmiş deneme kuralları (KB-217, KB-407, KB-504, KB-602, KB-706) |
| Chunking | `##` başlıklarına göre; en fazla 900 karakter, 150 karakter örtüşme. Her chunk'ta doküman, bölüm ve içindeki kural kimlikleri metadata olarak tutulur |
| Embedding | Ollama `bge-m3` (çok dilli). Alakasız kaynakları elemek için benzerlik eşiği 0,50 |
| Vector search | Kosinüs benzerliği + hibrit bonus: sorgudaki kural kimliği chunk'ta da geçiyorsa +0,15. Alakasız sorgular için benzerlik eşiği var |
| Context injection | Kaynaklar `[n]` numarasıyla prompt'a eklenir. Sistem talimatı yalnızca bu kaynakların kullanılmasını ve atıf yapılmasını ister |
| LLM | Ollama `qwen2.5:3b` |
| Reasoning akışı | (1) sinyal çıkarımı → (2) sorgu üretimi → (3) retrieval ve tekilleştirme → (4) context injection → (5) JSON değerlendirme → (6) **atıf doğrulama**: LLM'in andığı KB kimlikleri getirilen kaynaklarda yoksa sonuç "doğrulanmamış" olarak işaretlenir |

Local LLM tercihi bilinçli: işlem verisi kurum dışına çıkmaz (KB-805).

---

## 5. Agentic AI (Adım 9)

| Agent | Yetenek | Kimlerle konuşur |
|---|---|---|
| Orchestrator | `analyze_transaction` | Görevleri devreder (DELEGATE) |
| FeatureAgent | `features` | ScoringAgent'tan istek alır |
| ScoringAgent | `score` | Feature için FeatureAgent'a istek gönderir (REQUEST) |
| ContextAgent | `context_adjust` | — |
| RuleAgent | `evaluate_rules` | — |
| KnowledgeAgent | `retrieve_policy`, `reason_transaction` | InvestigatorAgent'tan istek alır |
| InvestigatorAgent | `investigate` | Politika için KnowledgeAgent'a istek gönderir (2 kez) |

* **İletişim:** Tipli mesajlar (`Message`) ve bir `MessageBus` kullanılır. Performative türleri: REQUEST, DELEGATE, RESULT, FAILURE. Tüm mesajlar log'lanır ve konuşma bazında izlenebilir.
* **Görev devri:** Orkestratör agent adını bilmez. Bus, yetenek kaydından görevi yapabilen agent'ı bulur. Yeni bir agent eklemek için kaydetmek yeterlidir.
* **İş akışı:** Plan; Ollama varsa LLM ile üretilip kayıtlı yeteneklere göre doğrulanır, yoksa varsayılan plan kullanılır. Düşük riskli ve risk kuralı tetiklenmemiş işlemlerde inceleme adımı atlanır (hızlı yol); LLM maliyeti yalnızca gerekli vakalarda harcanır.

---

## 6. API (Adım 10)

`uvicorn fraudai.api.main:app`. Ayrıntılar için `README.md` ve `/docs` (Swagger) sayfasına bakın.

* **Modüler yapı:** Router'lar konu bazlı ayrılmış (scoring, rules, rag, agents). İstekler Pydantic şemalarıyla doğrulanır. Servis katmanı `Depends` ile enjekte edilir ve testte kolayca değiştirilebilir.
* **Genişletilebilirlik:** Yeni bir bileşen `FraudService`'e, yeni bir endpoint ise yeni bir router'a eklenir.
* **Hata yönetimi:** 404 (işlem yok), 422 (geçersiz istek veya kural).
* **İki skorlama modu:** `transaction_id` (batch skorlanmış veri) ve `transaction` (ham kayıt, online skorlama).
  * Online skorlama, notebook'taki batch mantığının birebir karşılığıdır (`fraudai/scoring.py`). Akış simülasyonunda batch skorla Spearman korelasyonu 0,986.
  * `update_state=true` ile her işlem kullanıcı durumunu günceller (akış modu).

---

## 7. Sınırlılıklar ve geliştirme önerileri

* **Saat dilimi bilinmiyor.** Yerel saat, hacim çukurundan tahmin edildi; gerçek sistemde işlem saat dilimi kullanılmalı.
* **Kural isabetleri düşük frekanslı.** R001 test döneminde yalnızca 7 işlemde tetiklendi. İsabetleri daha uzun bir dönemde izlenmeli.
* **Context çarpanları ve kural eşikleri statik.** Analist geri bildirimi ve chargeback verisiyle periyodik olarak yeniden kalibre edilmeli (KB-707). Ağırlık optimizasyonu, çarpan ızgarası üzerinde arama ile otomatikleştirilebilir.
* **Model boyutu.** Varsayılan `qwen2.5:3b` modeli zaman zaman kuralların koşullarını birleştirebiliyor veya atıf eklemeyi atlayabiliyor. Donanım el veriyorsa `qwen2.5:7b` daha tutarlı sonuç verir (`config/settings.yaml`).
* **Online skorlamada `segment_volume_spike` bileşeni hesaplanmıyor.** Akış hâlinde segment hacmi tutularak eklenebilir.
