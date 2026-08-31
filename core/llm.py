"""Metin üretimi: RSS adayları arasından en uygununu seçer VE görsel/caption
için metinleri üretir — TEK bir yapılandırılmış (JSON) çağrıda. Sağlayıcı
(Gemini / Groq / Claude) config.yaml'daki llm.provider alanından seçilir.

Neden tek çağrıda seçim+üretim: mevcut manuel iş akışında bu değerlendirmeyi
(gerçek haber mi / Ankara ile alakalı mı / SEO-farming mi / daha önce
işlenmiş bir olayın tekrarı mı) bir dil modeli (Claude) yapıyordu. Aynı
yargıyı burada da bir LLM'e bırakmak, kırılgan regex kurallarından çok daha
güvenilir sonuç veriyor.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests

from .rss_fetch import NewsItem

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Selection:
    selected_guid: Optional[str]
    badge: str = ""
    headline: str = ""
    summary: str = ""
    caption: str = ""
    reason: str = ""


BASE_RULES = """Sen bir yerel haber sosyal medya editörüsün. Sana aday haberlerin bir
listesi verilecek (RSS'ten çekildi). Görevin:

1. Listeden TEK BİR haberi seç — Instagram'da paylaşılmaya en uygun olanı.
   Şu kriterlere göre ELE:
   - SEO/tıklama tuzağı sorular ("... ne zaman bitecek?", "... kaç oldu?" gibi
     merak uyandırıp cevap vermeyen başlıklar) ELENİR.
   - Liste/derleme içerikleri ("işte...", "yapay zekaya göre..." gibi) ELENİR.
   - Hedef bölgeyle doğrudan ilgisi olmayan genel/ulusal haberler ELENİR.
   - Aynı olayın/konunun başka bir adayla anlamca TEKRARI varsa sadece birini seç.
   - Görseli olmayan/görseli konuyla alakasız olan aday ELENİR.
   - Hiçbir aday uygun değilse selected_guid alanını null yap.
2. Seçilen haber için şu metinleri ÜRET (dil: Türkçe, resmi ama canlı bir
   yerel haber ajansı üslubu):
   - badge: en fazla 2 kelime / ~8 karakter, kategori etiketi (örn: "Gündem",
     "Kaza", "Kutlama", "Trafik").
   - headline: görselin üzerine yazılacak başlık, 1-2 KISA cümle (en fazla
     ~100 karakter, ekranda en fazla 3 satıra sığmalı).
   - summary: görselin altındaki panelde gösterilecek EN AZ 3 CÜMLELİK, olayı
     biraz daha detaylandıran özet (yaklaşık 180-260 karakter, en fazla 5
     satıra sığmalı — çok kısa/tek cümlelik özet YETERSİZ sayılır).
   - caption: Instagram paylaşım açıklaması. 2-3 cümle (150-220 karakter),
     sonunda 3-4 adet ilgili hashtag (mutlaka #Ankara ve verilen proje
     hashtag'i dahil olmalı).

SADECE aşağıdaki JSON şemasıyla, başka hiçbir açıklama/markdown olmadan cevap ver:
{"selected_guid": "<guid ya da null>", "badge": "...", "headline": "...", "summary": "...", "caption": "...", "reason": "<neden bu haberi seçtiğinin ya da hiçbirini seçmediğinin 1 cümlelik kısa açıklaması>"}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK_RE.search(text)
        if m:
            return json.loads(m.group(0))
        raise


def build_prompt(candidates: list[NewsItem], project_extra_rules: str, project_hashtag: str) -> str:
    lines = [BASE_RULES]
    if project_extra_rules:
        lines.append(f"\nProjeye özel ek kurallar:\n{project_extra_rules}\n")
    lines.append(f"\nCaption'da mutlaka bulunması gereken proje hashtag'i: {project_hashtag}\n")
    lines.append("\nAday haberler:\n")
    for it in candidates:
        lines.append(
            f"- guid: {it.guid}\n"
            f"  başlık: {it.title}\n"
            f"  özet: {it.summary[:300]}\n"
            f"  tarih: {it.published.isoformat()}\n"
        )
    return "\n".join(lines)


def _raise_with_body(resp: requests.Response) -> None:
    """resp.raise_for_status() hata govdesini (API'nin gercek hata mesajini)
    gizliyor - GitHub Actions loglarinda sadece "400/429 Client Error" gorunup
    asil sebep (kota, kredi, gecersiz model, vb.) kayboluyordu. Bu, HTTPError'i
    yanit govdesiyle birlikte firlatir ki log'da gercek mesaj gorulsun."""
    if resp.status_code >= 400:
        raise requests.exceptions.HTTPError(
            f"{resp.status_code} {resp.reason} - yanit govdesi: {resp.text[:2000]}",
            response=resp,
        )


def _call_gemini(prompt: str, model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY tanımlı değil")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "response_mime_type": "application/json"},
    }
    resp = requests.post(url, json=body, timeout=60)
    _raise_with_body(resp)
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(prompt: str, model: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY tanımlı değil")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    _raise_with_body(resp)
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_claude(prompt: str, model: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY tanımlı değil")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    _raise_with_body(resp)
    data = resp.json()
    return data["content"][0]["text"]


_PROVIDERS = {
    "gemini": (_call_gemini, "gemini-2.5-flash"),
    "groq": (_call_groq, "llama-3.3-70b-versatile"),
    "claude": (_call_claude, "claude-haiku-4-5-20251001"),
}


def generate_selection(
    candidates: list[NewsItem],
    llm_config: dict,
    project_extra_rules: str = "",
    project_hashtag: str = "#Ankara",
) -> Selection:
    provider_key = llm_config.get("provider", "gemini")
    if provider_key not in _PROVIDERS:
        raise ValueError(f"Bilinmeyen llm.provider: {provider_key}")
    call_fn, default_model = _PROVIDERS[provider_key]
    model = llm_config.get("model", default_model)

    prompt = build_prompt(candidates, project_extra_rules, project_hashtag)
    raw_text = call_fn(prompt, model)
    parsed = _extract_json(raw_text)

    return Selection(
        selected_guid=parsed.get("selected_guid") or None,
        badge=(parsed.get("badge") or "").strip(),
        headline=(parsed.get("headline") or "").strip(),
        summary=(parsed.get("summary") or "").strip(),
        caption=(parsed.get("caption") or "").strip(),
        reason=(parsed.get("reason") or "").strip(),
    )
