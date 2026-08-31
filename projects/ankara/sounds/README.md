# Arka plan sesleri

Bu klasöre .mp3 dosyaları koyun (örn. `haber1.mp3`, `alarm.mp3`, `tempo.mp3`...).
Her video üretiminde bunlardan RASTGELE biri arka plan sesi olarak eklenir —
böylece art arda gelen haberlerin sesi birbirinin aynısı olmaz.

Kurallar:
- Sadece `.mp3` uzantılı dosyalar taranır.
- Ses klip videodan kısaysa otomatik döner (loop), uzunsa videonun süresinde
  kesilir ve son yarım saniyede kısılarak (fade-out) biter — ani kesilme olmaz.
- Bu klasör boşsa (ya da hiç yoksa) video sessiz üretilir, hata vermez.
- Telif hakkı olmayan / kullanım izni olan sesler kullanmaya dikkat edin
  (Instagram'ın kendi ücretsiz ses kütüphanesi, telifsiz "royalty-free" efekt
  siteleri gibi kaynaklar uygun olur).
