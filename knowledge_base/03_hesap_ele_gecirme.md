# Hesap Ele Geçirme (Account Takeover) Politikası

> Kurgusal politika dokümanı (case çalışması).

## Belirtiler

Hesap ele geçirmede (ATO) dolandırıcı, gerçek kullanıcının kart veya hesap bilgilerini kendi cihazından kullanır. Tipik belirtiler: geçmişi olan kullanıcıda ilk kez görülen cihaz, yeni e-posta adresi, olağandışı saat ve kullanıcının alışık olmadığı yüksek tutar.

## Kurallar

KB-301: Yerleşik bir kullanıcı yerel saatle 00:00–05:59 arasında ilk kez yeni bir cihaz kullanırsa işlem REVIEW kuyruğuna alınır (rule engine R007).

KB-302: Gece saatinde (00:00–05:59), 200 USD üzerinde ve yeni cihazdan veya fatura adresi olmadan yapılan işlemler BLOCK edilir (rule engine R001). Bu kural en yüksek önceliğe sahiptir ve beyaz liste kuralları tarafından geçersiz kılınamaz.

KB-303: Kullanıcının şimdiye kadar 5 veya daha fazla farklı cihaz kullanması tek başına karar sebebi değildir. Ancak risk skoruna +3 puan eklenir (R008) ve inceleme notuna yazılır.

KB-304: Kullanıcının şimdiye kadar 3 veya daha fazla farklı e-posta alan adı kullanması kimlik karışıklığı veya sentetik kimlik işaretidir; risk skoruna +3 puan eklenir (R009).

## Analist adımları

KB-305: ATO şüphesiyle incelenen işlemde analist (1) cihazın daha önce başka kullanıcılarca kullanılıp kullanılmadığını, (2) e-posta değişikliğinin işlemden önceki 24 saatte yapılıp yapılmadığını, (3) teslimat adresinin değişip değişmediğini kontrol eder. İki veya daha fazla madde doğrulanırsa işlem BLOCK edilir ve kart sahibi aranır.
