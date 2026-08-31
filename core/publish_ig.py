"""Instagram Graph API — statik görsel gönderisi yayınlama.
Akış: POST /{ig-user-id}/media (image_url, caption) -> creation_id
      -> durumu FINISHED olana kadar kısa kısa kontrol et
      -> POST /{ig-user-id}/media_publish (creation_id) -> media_id
      -> GET /{media_id}?fields=permalink
"""
from __future__ import annotations

import time

import requests

GRAPH_VERSION = "v21.0"
# ONEMLI: bu proje "Instagram API with Instagram Login" (IGAA... on ekli token,
# dogrudan Instagram Business Login ile alinan) kullaniyor. Bu token turu SADECE
# graph.instagram.com tarafindan taniniyor - graph.facebook.com'a gonderilirse
# Meta "Cannot parse access token" hatasi doner (token gecerli olsa bile).
GRAPH_BASE = f"https://graph.instagram.com/{GRAPH_VERSION}"


class PublishError(RuntimeError):
    pass


def _check(resp: requests.Response) -> dict:
    if resp.status_code >= 400:
        raise PublishError(f"Graph API hatası ({resp.status_code}): {resp.text}")
    return resp.json()


def create_media_container(business_id: str, access_token: str, image_url: str, caption: str) -> str:
    url = f"{GRAPH_BASE}/{business_id}/media"
    data = _check(requests.post(url, data={
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token,
    }, timeout=60))
    return data["id"]


def create_reels_container(business_id: str, access_token: str, video_url: str, caption: str) -> str:
    url = f"{GRAPH_BASE}/{business_id}/media"
    data = _check(requests.post(url, data={
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }, timeout=60))
    return data["id"]


def wait_until_ready(creation_id: str, access_token: str, timeout_s: int = 90, interval_s: int = 5) -> None:
    url = f"{GRAPH_BASE}/{creation_id}"
    elapsed = 0
    while elapsed < timeout_s:
        data = _check(requests.get(url, params={"fields": "status_code", "access_token": access_token}, timeout=30))
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise PublishError(f"Medya işlenirken hata oluştu: {data}")
        time.sleep(interval_s)
        elapsed += interval_s
    # Görseller genelde saniyeler içinde hazır olur; zaman aşımında yine de
    # publish denemesi yapılabilir (Meta bazen status_code alanını hiç
    # doldurmuyor) — bu yüzden burada sessizce devam ediyoruz.


def publish(business_id: str, access_token: str, creation_id: str) -> str:
    url = f"{GRAPH_BASE}/{business_id}/media_publish"
    data = _check(requests.post(url, data={
        "creation_id": creation_id,
        "access_token": access_token,
    }, timeout=60))
    return data["id"]


def get_permalink(media_id: str, access_token: str) -> str:
    url = f"{GRAPH_BASE}/{media_id}"
    data = _check(requests.get(url, params={"fields": "permalink", "access_token": access_token}, timeout=30))
    return data.get("permalink", "")


def publish_image_post(business_id: str, access_token: str, image_url: str, caption: str) -> dict:
    creation_id = create_media_container(business_id, access_token, image_url, caption)
    wait_until_ready(creation_id, access_token)
    media_id = publish(business_id, access_token, creation_id)
    permalink = get_permalink(media_id, access_token)
    return {"media_id": media_id, "permalink": permalink}


def publish_reels_post(business_id: str, access_token: str, video_url: str, caption: str) -> dict:
    creation_id = create_reels_container(business_id, access_token, video_url, caption)
    # Video işlenmesi görsele göre daha uzun sürebilir (Meta tarafında encode/validate).
    wait_until_ready(creation_id, access_token, timeout_s=240, interval_s=8)
    media_id = publish(business_id, access_token, creation_id)
    permalink = get_permalink(media_id, access_token)
    return {"media_id": media_id, "permalink": permalink}


def verify_token(business_id: str, access_token: str) -> dict:
    """Salt-okunur doğrulama — token geçerli mi, doğru hesaba mı bağlı? Yayın yapmaz."""
    url = f"{GRAPH_BASE}/{business_id}"
    return _check(requests.get(url, params={"fields": "username,name,ig_id", "access_token": access_token}, timeout=30))
