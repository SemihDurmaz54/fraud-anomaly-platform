# İnceleme ve Eskalasyon Prosedürü

> Kurgusal prosedür dokümanı (case çalışması).

## REVIEW kuyruğu

KB-701: REVIEW kararı verilen her işlem için analist ekranında şunlar gösterilir: nihai risk skoru, dört AI katmanının (column, multivariate, entity, temporal) skorları ve gerekçeleri, uygulanan context kuralları, tetiklenen ve geçersiz kılınan iş kuralları ve ilgili politika maddeleri.

KB-702: Analist işlemi inceledikten sonra üç karardan birini verir: onay, red (BLOCK) veya kart sahibiyle doğrulama (step-up). Her karar gerekçesiyle birlikte kaydedilir ve modelin geri bildirim verisine eklenir.

KB-703: Kuyruktaki işlemler önceliğe göre sıralanır: önce BLOCK önerisi olanlar, sonra C ürünü işlemleri (KB-503), sonra yüksek değerli müşteriler (KB-407), en son diğerleri.

## Eskalasyon

KB-704: Aynı kullanıcı (uid) için 24 saat içinde 2 veya daha fazla REVIEW kararı oluşursa vaka seviye-2 fraud ekibine eskale edilir.

KB-705: Fraud olduğu doğrulanan her vakada aynı cihazı veya aynı kart grubunu (card1) kullanan diğer kullanıcılar 7 gün süreyle izleme listesine alınır.

KB-706: (Deneme kuralı) Seviye-2 ekibi, BLOCK edilen işlemin kart sahibine 30 dakika içinde ulaşamazsa kartı kalıcı olarak kapatır ve yeni kart basım sürecini başlatır.

## Geri bildirim döngüsü

KB-707: Analist kararları ve chargeback bildirimleri haftalık olarak toplanır. Context çarpanları ve kural eşikleri aylık olarak bu verilerle yeniden kalibre edilir. Ağırlık ve çarpan değişiklikleri yalnızca kalibrasyon döneminde belirlenir ve ayrı bir test döneminde doğrulanmadan canlıya alınmaz.
