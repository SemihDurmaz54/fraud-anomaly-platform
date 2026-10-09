# Açıklanabilirlik ve Veri Gizliliği Politikası

> Kurgusal politika dokümanı (case çalışması).

## Açıklanabilirlik

KB-801: Otomatik olarak verilen her BLOCK ve REVIEW kararı insan tarafından okunabilir bir gerekçe içermelidir. Gerekçe; kararı veren kuralı, kuralın kanıt alanlarını (ör. tutar, saat, işlem sayısı) ve AI skorunun baskın katmanını içerir.

KB-802: AI modeli tek başına BLOCK kararı veremez. AI skoru yalnızca REVIEW kararı üretebilir (KB-104); BLOCK kararları yalnızca açıkça tanımlanmış iş kurallarıyla verilir.

KB-803: LLM tarafından üretilen değerlendirmeler yalnızca bilgi tabanındaki politika maddelerine atıf yapabilir. Kaynakta olmayan bir politika kimliğine atıf yapılırsa değerlendirme "doğrulanmamış" olarak işaretlenir ve analistin kararına esas alınmaz.

## Veri gizliliği

KB-804: Analist ekranında ve LLM'e gönderilen bağlamda kart numarası, isim veya tam adres gibi kişisel veriler yer almaz. Yalnızca kodlanmış alanlar (card1, addr1, e-posta alan adı) ve türetilmiş özellikler kullanılır.

KB-805: LLM çağrıları yalnızca kurum içinde çalışan local modellerle (ör. Ollama) yapılır. İşlem verisi harici LLM servislerine gönderilmez.

KB-806: Model kararları ve açıklamaları 10 yıl süreyle denetim kaydında saklanır.
