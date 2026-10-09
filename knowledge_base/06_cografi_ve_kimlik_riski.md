# Coğrafi Risk ve Kimlik Doğrulama Politikası

> Kurgusal politika dokümanı (case çalışması).

## Coğrafi doğrulama

KB-601: Fatura adresi (addr1) ve mesafe (dist1) bilgisi olmayan işlemlerde coğrafi doğrulama yapılamaz. Bu işlemlerin risk skoruna +3 puan eklenir (rule engine R011). Tarihsel verilerde adresi olmayan işlemlerin fraud oranı yaklaşık %11'dir.

KB-602: (Deneme kuralı) Fatura adresi olmayan ve gece saatinde yapılan 200 USD üzeri işlemler, yabancı ülke işlemi gibi değerlendirilir ve BLOCK kuralı KB-302 kapsamına girer.

## E-posta tutarlılığı

KB-603: Ödeyen (P_emaildomain) ve alıcı (R_emaildomain) e-posta alan adlarının farklı olması tek başına fraud göstergesi değildir; hediye ve üçüncü kişi adına yapılan alımlarda yaygındır. Risk skoruna +2 puan eklenir (R010).

KB-604: Anonim e-posta servislerinden (ör. anonymous.com, protonmail.com) yapılan işlemlerde ek kimlik doğrulama (3DS) istenebilir. Ancak geçmiş verilerde bu işlemlerin alarm isabeti düşüktür (%5); bu yüzden otomatik REVIEW kuralı tanımlanmamıştır.

## Yeni kart ve yeni kullanıcı

KB-605: İlk kullanımından bu yana en fazla 1 gün geçmiş bir kartla, online kimlik bilgisi olan (cihaz verisi gelen) ve 500 USD veya üzerinde yapılan işlemler REVIEW kuyruğuna alınır (rule engine R005).

KB-606: Hiç geçmişi olmayan bir kullanıcıdan gelen 2000 USD üzerindeki işlemlerin risk skoruna +5 puan eklenir (R006). Bu kural tek başına karar vermez, çünkü yeni müşterilerin büyük alımları çoğunlukla meşrudur.

KB-607: Kullanıcının geçmiş ortalamasının 5 katı veya üzerindeki tutarlar (en az 3 geçmiş işlem varsa) risk skoruna +5 puan ekler (R004).
