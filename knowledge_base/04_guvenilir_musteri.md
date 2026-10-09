# Güvenilir Müşteri ve Beyaz Liste Politikası

> Kurgusal politika dokümanı (case çalışması).

## Güvenilir müşteri tanımı

KB-401: Bir kullanıcı şu koşulların tamamını sağlıyorsa güvenilir müşteri kabul edilir: en az 5 geçmiş işlem, en az 30 günlük geçmiş, işlemde yeni cihaz veya yeni e-posta kullanılmaması ve işlem tutarının kullanıcının geçmiş ortalamasının 1/3 ile 3 katı arasında olması.

KB-402: Güvenilir müşterinin anomali skoru context kuralı CTX-05 ile 0,75 çarpanıyla düşürülür. Gerekçe: geçmişte tutarlı davranan müşterilerde istatistiksel sapmaların büyük çoğunluğu meşru işlemlerdir (alarm isabeti %10,7; diğer kullanıcılarda %17).

## Beyaz liste

KB-403: Güvenilir müşterinin context-adjusted skoru 80'in altındaysa ve son 1 saatte 5'ten az işlemi varsa işlem beyaz liste kuralıyla (R013) otomatik onaylanır. Beyaz liste, REVIEW kurallarını geçersiz kılar.

KB-404: Beyaz liste hiçbir koşulda BLOCK kurallarını (KB-302 / R001) geçersiz kılamaz.

KB-405: Beyaz listedeki bir müşteri için chargeback (ters ibraz) bildirilirse müşteri 90 gün boyunca beyaz listeden çıkarılır.

## Yüksek değerli müşteriler

KB-406: Bilinen bir kullanıcının 500 USD üzerindeki işlemleri veya geçmiş ortalaması 300 USD'nin üzerinde olan müşterilerin tutarlı işlemleri yüksek değerli müşteri işlemidir. Bu işlemlerin skoru CTX-07 ile 0,80 çarpanıyla düşürülür. Tutar tek başına risk göstergesi değildir; geçmiş verilerde bu segmentteki alarmların yalnızca %3,6'sı gerçek fraud çıkmıştır.

KB-407: (Deneme kuralı) Yüksek değerli müşterilerde REVIEW kararı verilirse inceleme 30 dakika içinde tamamlanmalıdır (öncelikli kuyruk).
