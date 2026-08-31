#!/usr/bin/env python3
"""Instagram/Facebook uzun ömürlü (long-lived) access token'ı yeniler.
Uzun ömürlü token'lar ~60 gün geçerlidir ve süresi dolmadan yenilenmelidir.

Kullanım:
  export META_APP_ID=...          # Meta Geliştirici Uygulaması ID'si
  export META_APP_SECRET=...      # Uygulama Ayarları > Temel bilgiler'den
  export CURRENT_ACCESS_TOKEN=... # şu anki (süresi yaklaşan) token
  python scripts/refresh_ig_token.py

Çıktıdaki yeni token'ı ilgili GitHub Secret'a (örn. IG_ACCESS_TOKEN_ANKARA)
kopyalayın.
"""
from __future__ import annotations

import os
import sys

import requests

GRAPH_VERSION = "v21.0"


def main() -> None:
    app_id = os.environ.get("META_APP_ID")
    app_secret = os.environ.get("META_APP_SECRET")
    current_token = os.environ.get("CURRENT_ACCESS_TOKEN")
    if not all([app_id, app_secret, current_token]):
        print("META_APP_ID, META_APP_SECRET ve CURRENT_ACCESS_TOKEN ortam değişkenleri gerekli.", file=sys.stderr)
        sys.exit(1)

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token"
    resp = requests.get(url, params={
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": current_token,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    print("Yeni token:")
    print(data["access_token"])
    print(f"\nGeçerlilik süresi (saniye): {data.get('expires_in', 'bilinmiyor')}")
    print("\nBu token'ı GitHub reposunda ilgili secret'a (örn. IG_ACCESS_TOKEN_ANKARA) yapıştırın.")


if __name__ == "__main__":
    main()
