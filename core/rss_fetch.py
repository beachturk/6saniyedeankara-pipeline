"""Bir projenin tüm RSS kaynaklarını çeker, tek bir normalize edilmiş
liste haline getirir ve tarihe göre (en yeni önce) sıralar."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Optional

import feedparser
import requests
from dateutil import parser as dateparser

_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)


def fetch_higher_res_image(link: str, timeout: int = 10):
    """RSS'teki kucuk thumbnail yerine, haberin kendi sayfasindaki og:image
    meta etiketinden (genelde cok daha yuksek cozunurluklu "hero" gorsel)
    URL ceker. Bulamazsa/basarisiz olursa None doner - cagiran taraf bu
    durumda RSS'in orijinal (kucuk) image_url'ine geri dusmeli. Gorsel
    kalitesi sikayeti uzerine eklendi: RSS thumbnail'leri cogu zaman cok
    kucuk (or. ~300x170) ve bunlari 1080x1804'e buyutmek belirgin
    bulaniklik/bozulmaya yol aciyordu."""
    if not link:
        return None
    try:
        resp = requests.get(
            link, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (content-pipeline)"},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception:
        return None
    m = _OG_IMAGE_RE.search(html) or _OG_IMAGE_RE_ALT.search(html)
    if m:
        return unescape(m.group(1))
    return None



@dataclass
class NewsItem:
    guid: str            # "<source_key>:<orijinal_guid>" — kaynaklar arası benzersiz
    source_key: str
    title: str
    summary: str          # HTML temizlenmiş kısa açıklama
    link: str
    image_url: Optional[str]
    published: datetime    # UTC


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return unescape(_TAG_RE.sub("", text)).strip()


def _extract_image(entry) -> Optional[str]:
    # 1) media_content / media_thumbnail
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media:
            url = media[0].get("url")
            if url:
                return url
    # 2) enclosures
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") or enc.get("href"):
            href = enc.get("href") or enc.get("url")
            if href:
                return href
    for link in entry.get("links", []) or []:
        if link.get("type", "").startswith("image"):
            return link.get("href")
    # 3) description/content içinde <img src="...">
    for field_name in ("summary", "description"):
        raw = entry.get(field_name)
        if raw:
            m = _IMG_SRC_RE.search(raw)
            if m:
                return m.group(1)
    if entry.get("content"):
        for c in entry["content"]:
            m = _IMG_SRC_RE.search(c.get("value", ""))
            if m:
                return m.group(1)
    return None


def _parse_date(entry) -> datetime:
    for key in ("published", "updated", "pubDate"):
        raw = entry.get(key)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, TypeError):
                continue
    return datetime.now(timezone.utc)


def fetch_source(source_key: str, url: str, timeout: int = 20) -> list[NewsItem]:
    parsed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0 (content-pipeline)"})
    items: list[NewsItem] = []
    for entry in parsed.entries:
        orig_guid = entry.get("id") or entry.get("guid") or entry.get("link", "")
        guid = f"{source_key}:{orig_guid}"
        title = _strip_html(entry.get("title", ""))
        summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))
        image_url = _extract_image(entry)
        published = _parse_date(entry)
        items.append(NewsItem(
            guid=guid,
            source_key=source_key,
            title=title,
            summary=summary,
            link=entry.get("link", ""),
            image_url=image_url,
            published=published,
        ))
    return items


def fetch_all(rss_sources: list[dict]) -> list[NewsItem]:
    """rss_sources: [{"key": "haberler", "url": "https://..."}, ...]"""
    all_items: list[NewsItem] = []
    for src in rss_sources:
        try:
            all_items.extend(fetch_source(src["key"], src["url"]))
        except Exception as exc:  # noqa: BLE001 - bir kaynağın çökmesi diğerlerini engellemesin
            print(f"[rss_fetch] UYARI: {src.get('key')} çekilemedi: {exc}")
    all_items.sort(key=lambda it: it.published, reverse=True)
    return all_items
