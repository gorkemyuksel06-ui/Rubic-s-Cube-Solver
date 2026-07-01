# Rubik Küp Çözücü Robot

Hacettepe Üniversitesi ELE402 bitirme projesi kapsamında geliştirilen otonom Rubik Küp çözücü robot. Sistem şu anda **Telekom Laboratuvarında** hazır kurulu motor sürücüleriyle birlikte takılı halde bulunmaktadır.

## Sistem Detayları
* **Yazılım & Donanım:** Kodların tamamı **Python** dilinde yazılmıştır ve **Raspberry Pi** üzerinde çalışmaktadır. Çalıştırmak için gereken tüm kodlar bu depoya yüklenmiştir.
* **Algoritma ve Tarama:** Küpün çözümü için **Kociemba algoritması** kullanılmaktadır. Tarama işlemi bu algoritmanın kuralına uygun olarak yapılır (Tarama **Yeşil** merkezli yüzden başlar ve belirlenen sırayla devam eder).
* **Mekanik Durum:** Sistemin 3D dosyaları depoya eklenmiştir. Yazılımsal olarak hiçbir sorun bulunmamaktadır; kodlar ve algoritma sorunsuz çalışmaktadır. Ancak **mekanik anlamda geliştirme yapılması gereklidir.** Projeyi devralacak kişilerin daha stabil bir mekanik tasarım üzerine yoğunlaşması tavsiye edilir.

## Arayüz (UI) İşlevleri
Sistemi kontrol etmek için geliştirilen arayüzün temel özellikleri ve işlevleri şunlardır:
* **Tarama Modülü:** Yeşil yüzden başlayarak Kociemba dizilimine göre küpün renk matrisini kameradan alır ve kaydeder.
* **Çözüm (Algoritma) Motoru:** Taranan güncel renk durumunu işleyerek küpü çözecek minimum hamle dizisini hesaplar.
* **Hareket (Motor) Kontrolü:** Hesaplanmış olan hamle dizisini, Raspberry Pi pinleri üzerinden doğrudan motor sürücülerine aktararak fiziksel çözümü başlatır.
* **Talimatlar ve Durum Paneli:** Tarama sırası, adım takibi ve sistemin o anki durumuyla ilgili kullanıcıya gerekli bilgileri sağlar.

> **Önemli Not:** Arayüz üzerinde sistemi kullanmak için gerekli tüm talimatlar halihazırda bulunmaktadır. Ancak sistemin veya kod bloklarının tam olarak arka planda ne yaptığını daha iyi anlamak isterseniz, ilgili kodları herhangi bir yapay zekaya atarak her şeyi madde madde ve kolayca öğrenebilirsiniz.

## Geliştiriciler
* Görkem Yüksel
* Özge Erdem
