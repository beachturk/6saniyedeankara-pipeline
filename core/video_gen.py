"""6 saniyelik, hafif animasyonlu dikey video üretimi (1080x1920, Reels).
core/image_gen.py'deki compose_layers() fonksiyonunu zamana göre değişen
parametrelerle (rozet parlaması, metin fade/slide-in, fotoğrafta yavaş
yakınlaşma) tekrar tekrar çağırıp kare kare (frame) üretir, sonra ffmpeg ile
MP4'e kodlar. MoviePy yerine doğrudan ffmpeg kullanılıyor — daha az bağımlılık,
daha öngörülebilir davranış.
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import image_gen

DEFAULT_FPS = 30
DEFAULT_DURATION_S = 6.0
AUDIO_FADE_OUT_S = 0.5
AUDIO_VOLUME = 0.85  # arka plan sesi biraz kısılıyor, tamamen baskın olmasın diye


def pick_random_sound(sounds_dir: Path | None) -> Path | None:
    """sounds_dir içindeki .mp3 dosyalarından rastgele birini seçer. Klasör
    yoksa/boşsa None döner (bu durumda video sessiz üretilir)."""
    if not sounds_dir:
        return None
    sounds_dir = Path(sounds_dir)
    if not sounds_dir.is_dir():
        return None
    mp3s = sorted(sounds_dir.glob("*.mp3"))
    if not mp3s:
        return None
    return random.choice(mp3s)

# Animasyon zamanlaması (saniye) — SIRALI: önce başlık tam gelir, 1sn bekler,
# sonra özet paneli belirir ve içindeki metin KELİME KELİME (klavyede yazılır
# gibi) dolar — izleyiciyi metnin bitmesine kadar ekranda tutmak için kasıtlı.
HEADLINE_IN_START, HEADLINE_IN_END = 0.10, 0.55
GAP_AFTER_HEADLINE = 1.0
SUMMARY_PANEL_START = HEADLINE_IN_END + GAP_AFTER_HEADLINE   # 1.55 — panel belirmeye başlar
SUMMARY_PANEL_POP_DURATION = 0.25                              # panelin kendisi bu sürede belirir
TYPING_WORDS_PER_SECOND = 6.5                                   # kelime kelime yazılma hızı
MIN_TYPING_DURATION = 0.8
HOLD_AFTER_TYPING = 2.0           # yazım bitince okumaya bırakılan ekstra süre
CURSOR_BLINK_HZ = 2.2
BADGE_PULSE_PERIOD = 1.1          # rozet "nefes alma/yanıp sönme" periyodu
ZOOM_END = 1.09                    # fotoğrafta video boyunca ulaşılan toplam yakınlaşma


def _ease_out_back(t: float) -> float:
    """Hafif 'pop' hissi veren easing (biraz aşıp geri oturur)."""
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _progress(t: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (t - start) / (end - start)))


def compute_duration(summary: str, min_duration_s: float = DEFAULT_DURATION_S,
                      max_duration_s: float = 10.0) -> float:
    """Özet metni ne kadar uzunsa video da (kelime kelime yazma efektine yer
    açmak için) o kadar uzar — ama min_duration_s'in altına inmez, sabit bir
    tavanın (max_duration_s) üstüne de çıkmaz."""
    word_count = len(summary.split())
    typing_duration = max(MIN_TYPING_DURATION, word_count / TYPING_WORDS_PER_SECOND)
    type_start = SUMMARY_PANEL_START + SUMMARY_PANEL_POP_DURATION
    needed = type_start + typing_duration + HOLD_AFTER_TYPING
    return max(min_duration_s, min(needed, max_duration_s))


def _frame_params(t: float, duration: float, summary_word_count: int) -> dict:
    headline_p = _progress(t, HEADLINE_IN_START, HEADLINE_IN_END)
    panel_p = _progress(t, SUMMARY_PANEL_START, SUMMARY_PANEL_START + SUMMARY_PANEL_POP_DURATION)
    type_start = SUMMARY_PANEL_START + SUMMARY_PANEL_POP_DURATION
    typing_duration = max(MIN_TYPING_DURATION, summary_word_count / TYPING_WORDS_PER_SECOND)
    type_end = type_start + typing_duration
    reveal_p = _progress(t, type_start, type_end)
    is_typing = type_start <= t < type_end
    cursor_on = is_typing and (int(t * CURSOR_BLINK_HZ * 2) % 2 == 0)

    zoom = 1.0 + (ZOOM_END - 1.0) * (t / duration)
    # rozet: sabit bir "nefes alma" pulsasyonu (0..1), her zaman biraz görünür kalır
    badge_pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(2 * math.pi * t / BADGE_PULSE_PERIOD))
    return {
        "zoom": zoom,
        "badge_pulse": badge_pulse,
        "headline_alpha": headline_p,
        "headline_scale": 0.85 + 0.15 * _ease_out_back(headline_p) if headline_p < 1 else 1.0,
        "summary_alpha": panel_p,
        "summary_scale": 0.85 + 0.15 * _ease_out_back(panel_p) if panel_p < 1 else 1.0,
        "summary_reveal": reveal_p,
        "summary_cursor": cursor_on,
    }


def render_video(
    photo_url: str,
    badge: str,
    headline: str,
    summary: str,
    handle: str,
    image_cfg: dict,
    output_path: Path,
    duration_s: float | None = None,
    fps: int = DEFAULT_FPS,
    max_duration_s: float = 10.0,
    sounds_dir: Path | None = None,
) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg bulunamadı — video üretimi için ffmpeg kurulu olmalı.")

    cfg = {**image_gen.DEFAULTS, **(image_cfg or {})}
    photo = image_gen.download_image(photo_url)
    summary_word_count = len(summary.split())

    # duration_s verilmemişse (ya da None ise) özetin uzunluğuna göre otomatik
    # hesaplanır — kelime kelime yazma efektinin sıkışmadan tamamlanması için.
    if duration_s is None:
        duration_s = compute_duration(summary, max_duration_s=max_duration_s)

    total_frames = max(1, int(duration_s * fps))

    with tempfile.TemporaryDirectory(prefix="ig_video_") as tmpdir:
        tmp = Path(tmpdir)
        for i in range(total_frames):
            t = i / fps
            params = _frame_params(t, duration_s, summary_word_count)
            frame = image_gen.compose_layers(
                photo, badge, headline, summary, handle, cfg, **params,
            )
            frame.save(tmp / f"frame_{i:05d}.jpg", quality=90)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        sound_file = pick_random_sound(sounds_dir)
        fade_start = max(0.0, duration_s - AUDIO_FADE_OUT_S)

        if sound_file:
            print(f"[video_gen] Arka plan sesi: {sound_file.name}")
            # -stream_loop -1: ses klipten kısaysa video boyunca döner.
            # -shortest + afade: videodan uzunsa videonun süresinde kesilir,
            # kesim ani olmasın diye son AUDIO_FADE_OUT_S saniyede kısılarak biter.
            cmd = [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(tmp / "frame_%05d.jpg"),
                "-stream_loop", "-1", "-i", str(sound_file),
                "-shortest",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-filter:a", f"volume={AUDIO_VOLUME},afade=t=out:st={fade_start:.2f}:d={AUDIO_FADE_OUT_S}",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-r", str(fps),
                str(output_path),
            ]
        else:
            print("[video_gen] Ses dosyası bulunamadı (sounds/ klasörü boş/yok) — sessiz video üretiliyor.")
            cmd = [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(tmp / "frame_%05d.jpg"),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-shortest",
                "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-r", str(fps),
                str(output_path),
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg hata verdi:\n{result.stderr[-4000:]}")

    return output_path
