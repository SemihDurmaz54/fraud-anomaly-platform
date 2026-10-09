# Velocity ve Card Testing Politikası

> Kurgusal politika dokümanı (case çalışması).

## Velocity tanımı

Velocity, bir kullanıcının (uid: kart + adres + kartın ilk kullanım günü) belirli bir zaman penceresindeki işlem sayısıdır. Ani yoğunlaşmalar (burst), çalıntı kart bilgilerinin hızla harcanmaya çalışıldığını gösterebilir.

## Velocity kuralları

KB-201: Hesabı bir günden yeni olan bir kullanıcı son 1 saat içinde 5 veya daha fazla işlem yaparsa işlem REVIEW kuyruğuna alınır (rule engine R002).

KB-202: Yerleşik ve sık işlem yapan kullanıcılarda (10+ geçmiş işlem, 30+ gün) yüksek işlem sıklığı normal davranış kabul edilir. Bu kullanıcılar için velocity eşiği uygulanmaz; anomali skoru context kuralı CTX-06 ile 0,85 çarpanıyla düşürülür.

KB-203: Velocity nedeniyle REVIEW'a düşen işlemde analist, son 24 saatteki tüm işlemlerin aynı cihazdan yapılıp yapılmadığını kontrol eder. Farklı cihazlardan gelen eşzamanlı işlemler BLOCK gerekçesidir.

## Card testing

Card testing, dolandırıcıların çalıntı kart bilgisinin geçerli olup olmadığını küçük tutarlı işlemlerle denemesidir. Başarılı denemeyi genellikle yüksek tutarlı bir işlem izler.

KB-204: 10 USD'nin altındaki bir işlem, aynı kullanıcının son 1 saatteki 3 veya daha fazla işleminden biri ise card testing şüphesiyle REVIEW kuyruğuna alınır (rule engine R003).

KB-205: Card testing şüphesi doğrulanırsa kart kalıcı olarak bloke edilir ve aynı kart grubunda (card1) son 24 saatte işlem yapan diğer kullanıcılar da incelemeye alınır.

KB-217: (Deneme kuralı) C ürününde, kredi kartı ile ve outlook.com uzantılı e-posta adresinden yapılan ardışık küçük işlemler, card testing ihtimaline karşı 2 saat bekletilir ve ardından tek seferde değerlendirilir.
