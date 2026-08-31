"""Canva + tarayıcı otomasyonu yerine: Pillow ile 1080x1920 (9:16) kare
kompozisyonu. `compose_layers()` TEK bir "frame" (kare) üretir — statik
görsel için tek seferde (render), animasyonlu video için ise time-varying
parametrelerle (badge parlaması, metin fade-in vb.) core/video_gen.py
tarafından defalarca çağrılır. Tamamen config.yaml'daki `image:` bölümünden
özelleştirilebilir (renkler, oranlar) — böylece her proje kendi görsel
kimliğini kullanabilir.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "NotoSans-Variable.ttf"
CANVAS_W, CANVAS_H = 1080, 1920

DEFAULTS = {
    "bg_color": "#0b1730",
    "badge_color": "#e63946",
    "badge_glow_color": "#ff6b6b",
    "badge_text_color": "#ffffff",
    "headline_color": "#ffffff",
    "headline_panel_color": "#000000",
    "headline_panel_opacity": 0.62,
    "summary_color": "#eef1f6",
    "summary_panel_color": "#000000",
    "summary_panel_opacity": 0.55,     # şeffaf, bir tık koyu
    "handle_color": "#c9d3e0",
    "photo_height_ratio": 0.94,        # fotoğraf neredeyse tüm kareyi kaplıyor (tam ekran haber fotoğrafı)
    "photo_crop_focus_y": 0.32,         # kırpma odak noktası yukarıda (konu/yüz kesilmesin)
    "photo_dim_opacity": 0.30,          # fotoğrafın TAMAMINA hafif koyu ton — hangi fotoğraf gelirse gelsin metin okunsun
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:  # noqa: BLE001 - font varyasyonu yoksa sessizce Regular kalır
        pass
    return f


def download_image(url: str, timeout: int = 20) -> Image.Image:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (content-pipeline)"})
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        w = draw.textlength(candidate, font=font)
        if w <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_focus_top(img: Image.Image, size: tuple[int, int], focus_y: float, zoom: float = 1.0) -> Image.Image:
    """Kaynak fotoğrafı hedef orana göre kırpıp doldurur. `focus_y` dikey kırpma
    odağı (0=üst, 0.5=orta, 1=alt) — haber fotoğraflarında konu/yüz genelde
    üstte olduğu için varsayılan yukarı yakın. `zoom` > 1.0 verilirse hafif bir
    yakınlaşma (Ken Burns) efekti için kaynaktan daha dar bir alan kırpılır."""
    target_w, target_h = size
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    zoom = max(zoom, 1.0)  # zoom<1 (uzaklaşma) desteklenmiyor; her zaman >=1

    # zoom arttıkça kırpma alanı küçülür (kaynaktan daha dar bir bölge alınır) -> yakınlaşmış görünür
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_h = src_h / zoom
        new_w = new_h * target_ratio
    else:
        new_w = src_w / zoom
        new_h = new_w / target_ratio

    new_w = min(new_w, src_w)
    new_h = min(new_h, src_h)
    x0 = (src_w - new_w) * 0.5
    y0 = max(0, min(src_h - new_h, (src_h - new_h) * focus_y))

    cropped = img.crop((int(x0), int(y0), int(x0 + new_w), int(y0 + new_h)))
    return cropped.resize((target_w, target_h), Image.LANCZOS)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _paste_rgba(base: Image.Image, layer: Image.Image, pos: tuple[int, int], alpha: float = 1.0,
                 scale: float = 1.0) -> None:
    """RGBA katmanı base üzerine yapıştırır. alpha<1 şeffaflaştırır, scale!=1
    katmanı kendi merkezi etrafında büyütüp/küçültür (pop-in efekti için)."""
    if alpha <= 0.001:
        return
    if scale != 1.0:
        new_w = max(1, int(layer.width * scale))
        new_h = max(1, int(layer.height * scale))
        resized = layer.resize((new_w, new_h), Image.LANCZOS)
        dx = (layer.width - new_w) // 2
        dy = (layer.height - new_h) // 2
        pos = (pos[0] + dx, pos[1] + dy)
        layer = resized
    if alpha < 0.999:
        r, g, b, a = layer.split()
        a = a.point(lambda v: int(v * alpha))
        layer = Image.merge("RGBA", (r, g, b, a))
    base.paste(layer, pos, layer)


def compose_layers(
    photo: Image.Image,
    badge: str,
    headline: str,
    summary: str,
    handle: str,
    cfg: dict,
    *,
    zoom: float = 1.0,
    badge_pulse: float = 1.0,       # 0..1 arası, rozet "parlama" yoğunluğu (blink efekti)
    headline_alpha: float = 1.0,
    headline_scale: float = 1.0,     # pop-in efekti için (0.9 -> 1.0 gibi)
    summary_alpha: float = 1.0,       # panelin kendisinin (kutunun) belirme opaklığı
    summary_scale: float = 1.0,
    summary_reveal: float = 1.0,      # 0..1 — kaç kelimenin göründüğü (klavyede yazılır gibi)
    summary_cursor: bool = False,      # yazarken yanıp sönen "|" imleci
) -> Image.Image:
    """Tek bir kare üretir. Statik görsel için tüm alpha/scale=varsayılan
    (tam görünür) çağrılır; video için core/video_gen.py bu değerleri zamana
    göre değiştirerek SIRALI animasyon yaratır (önce başlık, 1sn sonra özet)."""
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), cfg["bg_color"])
    draw = ImageDraw.Draw(canvas)

    # --- Fotoğraf: gerçek haber görseli, neredeyse tam ekran, hafif zoom ---
    photo_h = int(CANVAS_H * cfg["photo_height_ratio"])
    fitted = _fit_focus_top(photo, (CANVAS_W, photo_h), cfg["photo_crop_focus_y"], zoom=zoom)
    canvas.paste(fitted, (0, 0))

    # Fotoğrafın TAMAMINA hafif koyu ton — hangi fotoğraf gelirse gelsin (parlak/
    # yoğun renkli/karmaşık olsa bile) üzerindeki metin okunabilir kalsın.
    dim_opacity = cfg.get("photo_dim_opacity", 0.30)
    if dim_opacity > 0:
        dim_layer = Image.new("RGB", (CANVAS_W, photo_h), "#000000")
        canvas.paste(Image.blend(canvas.crop((0, 0, CANVAS_W, photo_h)), dim_layer, dim_opacity), (0, 0))

    # Fotoğrafın alt kısmında EKSTRA koyulaşan gradient — özet paneli için
    grad_h = int(photo_h * 0.5)
    grad_top = photo_h - grad_h
    gradient = Image.new("L", (1, grad_h), 0)
    for gy in range(grad_h):
        t = gy / grad_h
        gradient.putpixel((0, gy), int(200 * (t ** 1.6)))
    gradient = gradient.resize((CANVAS_W, grad_h))
    dark_overlay = Image.new("RGB", (CANVAS_W, grad_h), "#000000")
    canvas.paste(dark_overlay, (0, grad_top), gradient)

    if photo_h < CANVAS_H:
        draw.rectangle([0, photo_h, CANVAS_W, CANVAS_H], fill=cfg["bg_color"])

    margin = 56
    max_text_w = CANVAS_W - margin * 2

    # --- Rozet (badge) — kırmızı buton, hafif "parlama/nefes alma" efektiyle ---
    badge_font = _font("Bold", 34)
    pad_x, pad_y = 30, 16
    text_w = draw.textlength(badge.upper(), font=badge_font)
    badge_w = int(text_w + pad_x * 2)
    badge_h = 34 + pad_y * 2
    badge_x, badge_y = (CANVAS_W - badge_w) // 2, 56
    base_color = _hex_to_rgb(cfg["badge_color"])
    glow_color = _hex_to_rgb(cfg["badge_glow_color"])
    pulse_color = _lerp_color(base_color, glow_color, badge_pulse)
    glow_pad = int(6 * badge_pulse)
    if glow_pad > 0:
        glow_layer = Image.new("RGBA", (badge_w + glow_pad * 2, badge_h + glow_pad * 2), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        gd.rounded_rectangle(
            [0, 0, glow_layer.width, glow_layer.height],
            radius=(badge_h + glow_pad * 2) // 2,
            fill=(*glow_color, int(90 * badge_pulse)),
        )
        canvas.paste(glow_layer, (badge_x - glow_pad, badge_y - glow_pad), glow_layer)
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=badge_h // 2,
        fill=pulse_color,
    )
    draw.text(
        (badge_x + pad_x, badge_y + pad_y - 4),
        badge.upper(),
        font=badge_font,
        fill=cfg["badge_text_color"],
    )

    # --- Başlık — ÜST kısımda, kendi (kırmızı/siyah) panelinin üzerinde, pop-in ---
    headline_font = _font("ExtraBold", 50)
    headline_lines = _wrap_to_width(draw, headline, headline_font, max_text_w - 80)[:3]
    headline_bottom_y = badge_y + badge_h + 34   # başlık yoksa bile açıklama için makul bir varsayılan
    if headline_lines:
        line_h = 60
        pad_x_h, pad_y_h = 40, 28
        panel_w = min(int(max(draw.textlength(l, font=headline_font) for l in headline_lines)) + pad_x_h * 2,
                      CANVAS_W - margin)
        panel_h = len(headline_lines) * line_h + pad_y_h * 2 - 14
        panel_x = (CANVAS_W - panel_w) // 2
        panel_y = badge_y + badge_h + 34

        panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle(
            [0, 0, panel_w, panel_h], radius=18,
            fill=(*_hex_to_rgb(cfg["headline_panel_color"]), int(255 * cfg["headline_panel_opacity"])),
        )
        ty = pad_y_h
        for line in headline_lines:
            lw = pd.textlength(line, font=headline_font)
            pd.text(((panel_w - lw) / 2, ty), line, font=headline_font,
                     fill=(*_hex_to_rgb(cfg["headline_color"]), 255))
            ty += line_h
        cx, cy = panel_x + panel_w / 2, panel_y + panel_h / 2
        _paste_rgba(canvas, panel, (int(cx - panel_w / 2), int(cy - panel_h / 2)),
                    alpha=headline_alpha, scale=headline_scale)
        headline_bottom_y = panel_y + panel_h

    # --- Özet (açıklama) — BAŞLIĞIN HEMEN ALTINDA, ORTALANMIŞ panel, pop-in ---
    summary_font = _font("Regular", 33)
    summary_lines = _wrap_to_width(draw, summary, summary_font, max_text_w - 100)[:5]
    if summary_lines:
        line_h_s = 44
        line_w = max(draw.textlength(line, font=summary_font) for line in summary_lines)
        panel_w = min(int(line_w) + 96, CANVAS_W - margin)
        panel_h = len(summary_lines) * line_h_s + 40
        panel_x = (CANVAS_W - panel_w) // 2
        panel_y = headline_bottom_y + 24

        panel = Image.new("RGBA", (panel_w, panel_h), (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        opacity = int(255 * cfg["summary_panel_opacity"])
        panel_draw.rounded_rectangle(
            [0, 0, panel_w, panel_h],
            radius=22,
            fill=(*_hex_to_rgb(cfg["summary_panel_color"]), opacity),
        )

        # Kaç kelime gösterilecek (klavyede yazılıyormuş gibi kelime kelime)
        total_words = sum(len(line.split()) for line in summary_lines)
        words_to_show = int(round(max(0.0, min(1.0, summary_reveal)) * total_words))
        cum_words = 0
        ty = 20
        cursor_drawn = False
        for line in summary_lines:
            line_words = line.split()
            wc = len(line_words)
            if cum_words + wc <= words_to_show:
                visible_text = line
                line_done = True
            elif cum_words >= words_to_show:
                visible_text = ""
                line_done = False
            else:
                visible_text = " ".join(line_words[: words_to_show - cum_words])
                line_done = False
            cum_words += wc

            if visible_text:
                lw = panel_draw.textlength(visible_text, font=summary_font)
                # tam satırlar ortalanır; yazılmakta olan satır aynı hizadan (satırın
                # tam hâlinin ortalanacağı x konumundan) başlayarak sola yaslı büyür
                full_lw = panel_draw.textlength(line, font=summary_font)
                x = (panel_w - full_lw) / 2
                panel_draw.text((x, ty), visible_text, font=summary_font,
                                 fill=(*_hex_to_rgb(cfg["summary_color"]), 255))
                if not line_done and summary_cursor and not cursor_drawn:
                    cursor_x = x + lw + 4
                    panel_draw.rectangle([cursor_x, ty + 4, cursor_x + 4, ty + line_h_s - 10],
                                          fill=(*_hex_to_rgb(cfg["summary_color"]), 255))
                    cursor_drawn = True
            elif not cursor_drawn and summary_cursor and cum_words - wc == words_to_show:
                # satır başına tam denk geldiyse imleç satırın başında yanıp söner
                full_lw = panel_draw.textlength(line, font=summary_font)
                x = (panel_w - full_lw) / 2
                panel_draw.rectangle([x, ty + 4, x + 4, ty + line_h_s - 10],
                                      fill=(*_hex_to_rgb(cfg["summary_color"]), 255))
                cursor_drawn = True
            ty += line_h_s

        cx, cy = panel_x + panel_w / 2, panel_y + panel_h / 2
        _paste_rgba(canvas, panel, (int(cx - panel_w / 2), int(cy - panel_h / 2)),
                    alpha=summary_alpha, scale=summary_scale)

    # --- Alt bilgi (hesap adı), ortalanmış ---
    handle_font = _font("SemiBold", 28)
    hw = draw.textlength(handle, font=handle_font)
    draw.text(((CANVAS_W - hw) / 2, CANVAS_H - 50), handle, font=handle_font, fill=cfg["handle_color"])

    return canvas


def render(
    photo_url: str,
    badge: str,
    headline: str,
    summary: str,
    handle: str,
    image_cfg: dict,
    output_path: Path,
) -> Path:
    """Statik (tek kare) görsel üretimi — video kullanmayan projeler ya da
    önizleme/thumbnail ihtiyacı için."""
    cfg = {**DEFAULTS, **(image_cfg or {})}
    photo = download_image(photo_url)
    canvas = compose_layers(photo, badge, headline, summary, handle, cfg, badge_pulse=1.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "JPEG", quality=92)
    return output_path
