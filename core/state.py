"""Proje başına CSV tabanlı 'daha önce paylaşıldı mı' takip dosyası.
Mevcut manuel sistemle AYNI kolon düzenini kullanır, böylece eski
paylasilan_haberler.csv dosyaları doğrudan devam ettirilebilir:
guid,date,title,instagram_url,timestamp
"""
from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = ["guid", "date", "title", "instagram_url", "timestamp"]


def load_used_guids(path: Path) -> set[str]:
    """Hem tam guid'i ('kaynak:12345') hem de bare id'yi ('12345') döner —
    eski manuel CSV'lerde kaynak öneki tutarsız kullanılmıştı (bazı satırlarda
    var, bazılarında yok), bu yüzden ikisi de eşleşme kümesine eklenir."""
    if not path.exists():
        return set()
    used: set[str] = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            guid = row[0].strip()
            used.add(guid)
            if ":" in guid:
                used.add(guid.split(":", 1)[1])
    return used


def append_row(path: Path, guid: str, date: str, title: str, instagram_url: str, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([guid, date, title, instagram_url, timestamp])
