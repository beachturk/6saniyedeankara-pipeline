"""Instagram Graph API 'image_url' herkese açık bir HTTPS adresi istiyor.
Ayrı bir barındırma servisi kurmak yerine: üretilen görsel bu repoya
commit+push edilir, GitHub bunu otomatik olarak raw.githubusercontent.com
üzerinden herkese açık şekilde sunar — ekstra maliyet YOK."""
from __future__ import annotations

import os


def public_raw_url(relative_path: str) -> str:
    """relative_path: repo köküne göre yol, örn. 'public/ankara/xyz.jpg'"""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if not repo:
        raise RuntimeError(
            "GITHUB_REPOSITORY tanımlı değil — bu adım GitHub Actions içinde "
            "veya .env'de GITHUB_REPOSITORY/GITHUB_REF_NAME set edilerek çalıştırılmalı."
        )
    relative_path = relative_path.lstrip("/")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{relative_path}"
