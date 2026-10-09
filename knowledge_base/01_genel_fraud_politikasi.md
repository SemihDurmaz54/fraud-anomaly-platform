# Genel Fraud Önleme Politikası

> Bu doküman case çalışması için hazırlanmış **kurgusal** bir politikadır. Kural kimlikleri (KB-xxx) gerçek bir kurumu temsil etmez.

## Amaç ve kapsam

Bu politika, kartlı online ödemelerde fraud ve anomali tespitinin nasıl yapılacağını tanımlar. Tüm işlemler gerçek zamanlı olarak üç katmandan geçer: AI tabanlı anomali skoru, bağlama göre skor düzeltme (context adjust) ve iş kuralları (rule engine). Nihai karar APPROVE, REVIEW veya BLOCK olabilir.

## Karar kategorileri

KB-101: APPROVE kararı verilen işlemler otomatik onaylanır ve yalnızca denetim kaydına yazılır.

KB-102: REVIEW kararı verilen işlemler manuel inceleme kuyruğuna alınır. İnceleme en geç 2 saat içinde tamamlanmalıdır. Bu süre içinde işlem askıda (pending) bekletilir.

KB-103: BLOCK kararı verilen işlemler reddedilir. Kart sahibine SMS ile bilgi verilir ve kart, kart sahibi doğrulama yapana kadar 24 saat geçici blokede tutulur.

## Risk skoru eşikleri

KB-104: Context-adjusted anomali skoru 95 ve üzerindeki işlemler, hiçbir iş kuralı tetiklenmese bile REVIEW kuyruğuna alınır (bkz. rule engine R012).

KB-105: Nihai risk skoru (anomali skoru + kural katkıları) 0–100 aralığındadır. Kuralların skora toplam katkısı ±30 puanla sınırlıdır; böylece tek bir kural grubu AI değerlendirmesini tamamen geçersiz kılamaz.

## Kural önceliği ve çatışma çözümü

KB-106: Birden fazla kural aynı anda tetiklendiğinde öncelik numarası en küçük olan kural kararı belirler. BLOCK kuralları (öncelik 1) her zaman beyaz liste kurallarından önce gelir. Beyaz liste (ALLOW) kuralları ise REVIEW kurallarını geçersiz kılabilir.

KB-107: Geçersiz kılınan kurallar karar gerekçesinde mutlaka listelenir. Analist, geçersiz kılınan bir REVIEW kuralını gerekçe göstererek yeniden aktive edebilir.
