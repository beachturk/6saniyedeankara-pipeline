"""HTML tabanlı (RSS'i OLMAYAN) kaynaklar için basit, hedefe özel scraper'lar.

core/rss_fetch.py sadece gerçek RSS/XML feed'lerini (feedparser ile)
okuyabiliyor. Bazı kaynaklarda (örn. Çankaya Belediyesi'nin resmi haber
sayfası) RSS hiç yok - sadece düz HTML liste var. Bu modül o kaynaklar
için düzenli-ifade tabanlı, hedefe özel ("bu site için yazıldı, genel
amaçlı değil") scraper'lar barındırır.

ÖNEMLİ KIRILGANLIK UYARISI: RSS'in aksine bu scraper'lar sitenin HTML
yapısına doğrudan bağımlı. Site tasarımı/şablonu değişirse scraper'lar
SESSİZCE boş liste dönebilir (hata fırlatmaz, pipeline.py diğer
kaynaklarla devam eder - bkz. fetch_all'daki try/except) ya da hatalı
veri çıkarabilir. Periyodik olarak gerçek çıktısı kontrol edilmeli.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape

import requests

from .rss_fetch import NewsItem, _strip_html

_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_BOILERPLATE_LINK_TEXTS = {"devamını oku", "devamini oku", "oku", "detay", "detaylar", ""}

_WINDOW_BEFORE = 800
_WINDOW_AFTER = 1500


def fetch_cankaya_bel(
    url: str = "https://www.cankaya.bel.tr/haberler",
    source_key: str = "cankayabel",
    timeout: int = 20,
) -> list[NewsItem]:
    """Çankaya Belediyesi'nin /haberler listesini çeker. Makale linkleri
    'https://www.cankaya.bel.tr/haberler/<slug>' biçiminde - bu desene göre
    eşleştiriyoruz (sitenin tek sabit/garanti kısmı bu; class adları vs.
    değişebilir, o yüzden onlara bağımlı olmadık). Her item için görsel/
    tarih/özet ararken, bir ÖNCEKİ ve bir SONRAKİ item eşleşmesinin sınırını
    AŞMIYORUZ ki art arda gelen item'ların görsel/tarihi birbirine karışmasın."""
    link_re = re.compile(
        r'<a[^>]+href=["\']('
        + re.escape("https://www.cankaya.bel.tr/haberler/")
        + r'[a-z0-9\-]+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (content-pipeline)"},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:  # noqa: BLE001 - bir kaynağın çökmesi diğerlerini engellemesin
        print(f"[html_scrape] UYARI: {source_key} çekilemedi: {exc}")
        return []

    matches = list(link_re.finditer(html))
    seen_links: set[str] = set()
    items: list[NewsItem] = []
    now = datetime.now(timezone.utc)

    for idx, m in enumerate(matches):
        link = m.group(1)
        title = _strip_html(m.group(2)).strip()
        if not title or title.lower() in _BOILERPLATE_LINK_TEXTS or link in seen_links:
            continue
        seen_links.add(link)
        slug = link.rsplit("/", 1)[-1]

        prev_end = matches[idx - 1].end() if idx > 0 else 0
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
        before = html[max(prev_end, m.start() - _WINDOW_BEFORE): m.start()]
        after = html[m.end(): min(next_start, m.end() + _WINDOW_AFTER)]

        # Görsel tipik olarak başlıktan ÖNCE gelir (item'ın en üstünde) -
        # "before" penceresindeki EN YAKIN (sondaki) eşleşmeyi al.
        img_matches = list(_IMG_RE.finditer(before))
        img_m = img_matches[-1] if img_matches else _IMG_RE.search(after)
        image_url = unescape(img_m.group(1)) if img_m else None

        # Tarih tipik olarak başlıktan SONRA gelir (özetin altında).
        date_m = _DATE_RE.search(after) or _DATE_RE.search(before)
        if date_m:
            try:
                # Sayfada sadece GÜN var, saat yok. 00:00 UTC alırsak bugünün
                # haberi bile max_age (36 sa) süzgecinde "eski" kalıp RSS
                # haberlerinin altına düşüyordu. Günün sonunu (TR 23:59 =
                # 20:59 UTC) al, ama gelecekte olamaz -> şu an ile sınırla.
                published = min(
                    datetime(
                        int(date_m.group(3)), int(date_m.group(2)), int(date_m.group(1)),
                        20, 59, tzinfo=timezone.utc,
                    ),
                    now,
                )
            except ValueError:
                published = now
        else:
            published = now

        p_m = _P_RE.search(after)
        summary = _strip_html(p_m.group(1)) if p_m else ""

        items.append(NewsItem(
            guid=f"{source_key}:{slug}",
            source_key=source_key,
            title=title,
            summary=summary,
            link=link,
            image_url=image_url,
            published=published,
        ))

    return items


PARSERS = {
    "cankaya_bel": fetch_cankaya_bel,
}


def fetch_all(html_sources: list[dict]) -> list[NewsItem]:
    """html_sources: [{"key": "cankayabel", "parser": "cankaya_bel", "url": "https://..."}, ...]"""
    all_items: list[NewsItem] = []
    for src in html_sources or []:
        parser_key = src.get("parser")
        fn = PARSERS.get(parser_key)
        if fn is None:
            print(f"[html_scrape] UYARI: bilinmeyen parser '{parser_key}' (key={src.get('key')})")
            continue
        try:
            all_items.extend(fn(url=src["url"], source_key=src["key"]))
        except Exception as exc:  # noqa: BLE001
            print(f"[html_scrape] UYARI: {src.get('key')} çekilemedi: {exc}")
    return all_items
