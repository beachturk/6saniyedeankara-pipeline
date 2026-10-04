"""Orkestrasyon. GitHub Actions'ta İKİ AŞAMALI çalışır çünkü Instagram
Graph API'nin image_url'i public olarak erişilebilir olmalı — görsel önce
push edilmeli, SONRA yayınlanabilir:

  1. generate(project)  -> RSS çek, LLM ile seç+metin üret, Pillow ile
                            görseli oluştur, projects/<key>/pending.local.json'a yaz.
                            (workflow burada git commit+push yapar)
  2. publish(project)   -> pending.local.json'u oku, artık public olan
                            raw.githubusercontent.com URL'ini hesapla,
                            Instagram Graph API'ye yayınla, state.csv'ye ekle,
                            pending.local.json'u siler.

dry_run(project) tek adımda çalışır, GERÇEK YAYIN YAPMAZ — sadece görseli
üretip yerelde bırakır (önizleme/test için).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import filters, html_scrape, image_gen, llm, publish_ig, rss_fetch, state, video_gen
from .config import ProjectConfig, load_project


def _safe_filename(guid: str, ext: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in guid)[:80] + ext


def _fetch_candidates(cfg: ProjectConfig) -> list[rss_fetch.NewsItem]:
    used = state.load_used_guids(cfg.state_csv_path)
    items = rss_fetch.fetch_all(cfg.rss_sources)
    # RSS'i olmayan (ör. cankaya.bel.tr) kaynaklar için HTML scraper'lar -
    # bkz. core/html_scrape.py. rss_fetch.fetch_all zaten kendi içinde
    # tarihe göre sıralıyor; buraya eklenen scraped item'larla BİRLİKTE
    # yeniden sıralamamız gerekiyor çünkü filters.prefilter sıralı geldiğini
    # varsayıp limit'e göre kesiyor.
    items += html_scrape.fetch_all(cfg.raw.get("html_sources", []))
    items.sort(key=lambda it: it.published, reverse=True)
    max_age_hours = cfg.filters.get("max_age_hours", 36)
    limit = cfg.filters.get("candidate_limit", 10)
    require_keywords = cfg.filters.get("require_keywords") or None
    trusted_sources = set(cfg.filters.get("trusted_sources") or [])

    # Teşhis logu (GitHub Actions'ta "neden içerik çıkmadı" sorusunu cevaplamak için)
    from collections import Counter
    print(f"[{cfg.key}] Çekilen toplam haber: {len(items)} "
          f"| kaynak bazında: {dict(Counter(it.source_key for it in items))}")

    candidates = filters.prefilter(
        items, used, max_age_hours=max_age_hours, limit=limit,
        require_keywords=require_keywords, trusted_sources=trusted_sources,
    )
    print(f"[aday] anahtar-kelime/tazelik/kullanılmamış filtresi sonrası aday sayısı: {len(candidates)}")
    for it in candidates:
        print(f"[aday]   {it.source_key} | {it.published.isoformat()} | {it.title[:90]}")
    return candidates


def generate(project_key: str) -> dict | None:
    cfg = load_project(project_key)
    candidates = _fetch_candidates(cfg)
    if not candidates:
        print(f"[{project_key}] Uygun aday yok (RSS boş ya da hepsi zaten paylaşılmış).")
        return None

    selection = llm.generate_selection(
        candidates,
        cfg.llm,
        project_extra_rules=cfg.filters.get("extra_rules", ""),
        project_hashtag=cfg.raw.get("hashtag", "#Haber"),
    )
    if not selection.selected_guid:
        print(f"[{project_key}] LLM uygun aday bulamadı. Sebep: {selection.reason}")
        return None

    chosen = next((it for it in candidates if it.guid == selection.selected_guid), None)
    if chosen is None:
        print(f"[{project_key}] UYARI: LLM'in seçtiği guid aday listesinde yok: {selection.selected_guid}")
        return None

    output_type = cfg.raw.get("output_type", "video")  # "video" (Reels) | "image" (feed post)
    ext = ".mp4" if output_type == "video" else ".jpg"
    output_filename = _safe_filename(chosen.guid, ext)
    output_path = cfg.public_dir / output_filename

    # Gorsel kalitesi sikayeti uzerine: RSS thumbnail'i genelde kucuk (~300x170)
    # oluyor ve bunu 1080x1804'e buyutmek belirgin bulaniklik/bozulmaya yol
    # aciyordu. Once haberin kendi sayfasindaki og:image'i (genelde cok daha
    # yuksek cozunurluklu) denenir; bulunamazsa RSS'in orijinal image_url'ine
    # geri duser.
    photo_url = rss_fetch.fetch_higher_res_image(chosen.link) or chosen.image_url

    common_kwargs = dict(
        photo_url=photo_url,
        badge=selection.badge,
        headline=selection.headline,
        summary=selection.summary,
        handle=cfg.raw.get("handle", ""),
        image_cfg=cfg.image,
        output_path=output_path,
    )
    video_duration_s = None
    if output_type == "video":
        video_cfg = cfg.raw.get("video", {})
        max_duration_s = video_cfg.get("max_duration_s", 10.0)
        # thumb_offset (Instagram kapak resmi) için videonun kaç saniye
        # süreceğini publish() aşamasında da bilmemiz lazım - render_video ile
        # BİREBİR AYNI fonksiyonla (video_gen.compute_duration) önceden
        # hesaplıyoruz ki iki yerde de aynı sonucu versin.
        video_duration_s = video_cfg.get("duration_s") or video_gen.compute_duration(
            selection.summary, max_duration_s=max_duration_s,
        )
        video_gen.render_video(
            **common_kwargs,
            duration_s=video_duration_s,
            max_duration_s=max_duration_s,
            fps=video_cfg.get("fps", video_gen.DEFAULT_FPS),
            sounds_dir=cfg.sounds_dir,  # projects/<proje>/sounds/*.mp3 -> rastgele arka plan sesi
        )
    else:
        image_gen.render(**common_kwargs)

    pending = {
        "guid": chosen.guid,
        "title": chosen.title,
        "caption": selection.caption,
        "output_type": output_type,
        "media_relative_path": str(output_path.relative_to(cfg.public_dir.parent.parent)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if video_duration_s is not None:
        pending["video_duration_s"] = video_duration_s
    cfg.pending_json_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{project_key}] {'Video' if output_type == 'video' else 'Görsel'} üretildi: {output_path} (guid={chosen.guid})")
    print(f"[{project_key}] Seçim gerekçesi: {selection.reason}")
    return pending


def publish(project_key: str) -> dict | None:
    cfg = load_project(project_key)
    if not cfg.pending_json_path.exists():
        print(f"[{project_key}] Bekleyen (pending) içerik yok, yayınlanacak bir şey bulunamadı.")
        return None
    pending = json.loads(cfg.pending_json_path.read_text(encoding="utf-8"))

    from . import hosting
    media_url = hosting.public_raw_url(pending["media_relative_path"])

    ig = cfg.instagram
    if pending.get("output_type", "video") == "video":
        # Kapak resmi (Instagram feed/profil ızgarasında görünen kare) videonun
        # SON saniyelerinden seçiliyor - o ana kadar rozet+başlık+özet metninin
        # TAMAMI yazılmış/görünür durumda oluyor (bkz. core/video_gen.py
        # HOLD_AFTER_TYPING). İlk kare (Meta varsayılanı) aksine animasyon
        # henüz başlamadan önceki neredeyse boş anı gösteriyordu.
        thumb_offset_ms = None
        video_duration_s = pending.get("video_duration_s")
        if video_duration_s:
            thumb_offset_ms = int(max(0.0, video_duration_s - 0.5) * 1000)
        result = publish_ig.publish_reels_post(
            business_id=ig["business_id"],
            access_token=ig["access_token"],
            video_url=media_url,
            caption=pending["caption"],
            thumb_offset_ms=thumb_offset_ms,
        )
    else:
        result = publish_ig.publish_image_post(
            business_id=ig["business_id"],
            access_token=ig["access_token"],
            image_url=media_url,
            caption=pending["caption"],
        )

    now = datetime.now(timezone.utc)
    state.append_row(
        cfg.state_csv_path,
        guid=pending["guid"],
        date=now.strftime("%Y-%m-%d"),
        title=pending["title"],
        instagram_url=result["permalink"],
        timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    cfg.pending_json_path.unlink(missing_ok=True)
    print(f"[{project_key}] Yayınlandı: {result['permalink']}")
    return result


def dry_run(project_key: str) -> dict | None:
    pending = generate(project_key)
    if pending:
        print(f"[{project_key}] DRY-RUN: gerçek yayın yapılmadı. Görsel ve caption yukarıda.")
        print(f"[{project_key}] Caption:\n{pending['caption']}")
    return pending
