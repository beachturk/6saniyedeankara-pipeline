"""Mekanik ön-filtreler. İnce eleme (Ankara-alaka, SEO-farming, dedup,
haber kalitesi) kasıtlı olarak LLM seçim adımına bırakılıyor — bu, insan
gözüyle 'bu gerçek bir haber mi, tekrar mı, alakalı mı' değerlendirmesine
en yakın sonucu veriyor. Burada sadece ucuz/mekanik elemeler var."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .rss_fetch import NewsItem


_TR_FOLD = str.maketrans("çğıöşü", "cgiosu")


def _fold(text: str) -> str:
    """Türkçe-güvenli küçük harfe çevirme + aksan sadeleştirme (ÇANKAYA /
    Çankaya / cankaya hepsi 'cankaya' olur). Python'ın varsayılan lower()'ı
    'I'->'i' yapıp 'KIZILAY'ı 'kizilay' yaptığı için önce İ/I'yı elle çeviriyoruz."""
    return (text or "").replace("İ", "i").replace("I", "ı").lower().translate(_TR_FOLD)


def _matches_keywords(it: NewsItem, folded_keywords: list[str]) -> bool:
    haystack = _fold(f"{it.title} {it.summary} {it.link}")
    return any(k in haystack for k in folded_keywords)


def prefilter(
    items: list[NewsItem],
    used_guids: set[str],
    max_age_hours: int = 36,
    limit: int = 10,
    require_keywords: list[str] | None = None,
    trusted_sources: set[str] | None = None,
) -> list[NewsItem]:
    """require_keywords verilirse (ör. ["Çankaya", "Kızılay"]), başlık/özet/
    link'inde bu kelimelerden HİÇBİRİ geçmeyen haberler `limit` kesmesinden
    ÖNCE elenir. Neden: ilçe-özel projede aday havuzu ~50-150 genel Ankara
    haberi; en yeni 10'u kesip sonra LLM'e 'bunlardan Çankaya olanı seç'
    demek, Çankaya haberlerini daha eski oldukları için havuza hiç sokmuyordu.
    trusted_sources'taki kaynaklar (ör. belediyenin kendi sitesi) zaten
    tamamen yerel olduğu için keyword kontrolünden muaf."""
    if require_keywords:
        folded = [_fold(k) for k in require_keywords if k]
        trusted = trusted_sources or set()
        items = [
            it for it in items
            if it.source_key in trusted or _matches_keywords(it, folded)
        ]

    def _already_used(it: NewsItem) -> bool:
        bare = it.guid.split(":", 1)[1] if ":" in it.guid else it.guid
        return it.guid in used_guids or bare in used_guids

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)

    fresh_with_image = [
        it for it in items
        if not _already_used(it)
        and it.image_url
        and it.title
        and it.published >= cutoff
    ]

    if fresh_with_image:
        return fresh_with_image[:limit]

    # Hiç taze aday yoksa: eski ama HENÜZ KULLANILMAMIŞ, görseli olan
    # haberlere gevşetilmiş (fallback) modda izin ver (manuel iş akışındaki
    # "roundup içerik" kuralının karşılığı).
    fallback = [
        it for it in items
        if not _already_used(it) and it.image_url and it.title
    ]
    return fallback[:limit]
