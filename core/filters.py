"""Mekanik ön-filtreler. İnce eleme (Ankara-alaka, SEO-farming, dedup,
haber kalitesi) kasıtlı olarak LLM seçim adımına bırakılıyor — bu, insan
gözüyle 'bu gerçek bir haber mi, tekrar mı, alakalı mı' değerlendirmesine
en yakın sonucu veriyor. Burada sadece ucuz/mekanik elemeler var."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .rss_fetch import NewsItem


def prefilter(
    items: list[NewsItem],
    used_guids: set[str],
    max_age_hours: int = 36,
    limit: int = 10,
) -> list[NewsItem]:
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
