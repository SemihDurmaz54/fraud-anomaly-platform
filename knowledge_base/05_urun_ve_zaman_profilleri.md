# Ürün ve Zaman Bazlı Risk Profilleri

> Kurgusal politika dokümanı (case çalışması).

## Ürün (ProductCD) risk profilleri

KB-501: W ürünü düşük riskli perakende ürünüdür (tarihsel fraud oranı yaklaşık %2). Bu üründe anomali skoru CTX-09 ile 0,90 çarpanıyla düşürülür.

KB-502: R ürünü düşük riskli kabul edilir (alarm isabeti yaklaşık %6). Skor CTX-08 ile 0,85 çarpanıyla düşürülür.

KB-503: C ürünü yüksek riskli üründür (tarihsel fraud oranı yaklaşık %11, ortalamanın 3 katı). C ürünündeki REVIEW işlemleri kuyruğun başına alınır.

KB-504: (Deneme kuralı) C ürününde aynı gün içinde 3'ten fazla farklı kartla işlem yapan cihazlar 7 gün süreyle izleme listesine alınır.

## Mesai saatleri

KB-505: Yerel saatle hafta içi 09:00–18:00 arası mesai saatidir. Bu saatlerde işlem hacmi yüksektir, fraud ekibi tam kadro çalışır ve alarmların isabeti düşüktür. Bu nedenle mesai saatindeki işlemlerin skoru CTX-01 ile 0,95 çarpanıyla hafifçe düşürülür.

KB-506: Yerel saatle 00:00–05:59 arası mesai dışıdır. Bu saatlerde fraud oranı ortalamanın yaklaşık 2 katıdır (%7,8). Skor CTX-02 ile 1,15 çarpanıyla artırılır.

## Hafta sonu

KB-507: Hafta sonu W ve R ürünlerinde perakende alışveriş hacmi doğal olarak artar. Bu artış anomali sayılmaz ve skor CTX-03 ile 0,90 çarpanıyla düşürülür.

KB-508: Hafta sonu REVIEW kuyruğu nöbetçi ekip tarafından yönetilir. Nöbetçi ekip yalnızca BLOCK ve 95 üzeri skorlu REVIEW işlemlerini aynı gün inceler; diğerleri pazartesi sabahı incelenir ve bu süre boyunca askıda kalmaz, onaylanır.
