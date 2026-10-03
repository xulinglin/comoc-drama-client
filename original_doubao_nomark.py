"""OriginalDoubao no-watermark video parsing helpers.

Only the OriginalDoubao video parser needed by this desktop application is included.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_FPLAY_KDF_SALT = "TdTC5rgxYgkOUrPHpnM7pByyRiuCmrWKGWs521cXdST0m69/COjWjSanLjfBqVovHwWlGJKu8pSXMrYqOKrdWA=="


_VIDEO_ID_PATTERNS = (
    re.compile(r'["\'](?:vid|video_id|uri)["\']\s*:\s*["\'](v[0-9a-z]{20,80})', re.IGNORECASE),
    re.compile(r"(?:[?&]|&amp;)video_id=([^&#\s\"']+)", re.IGNORECASE),
    re.compile(r"/video/fplay/(?:[^/?#]+/){2}(v[0-9a-z]{20,80})", re.IGNORECASE),
    re.compile(r"\b(v[0-9a-z]{20,80})\b", re.IGNORECASE),
)
_SHARE_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?doubao\.com/(?:thread/[^\s\"'<>]+|video-sharing\?[^\s\"'<>]+)",
    re.IGNORECASE,
)
_MEDIA_URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>]+/video/tos/[^\s\"'<>]+",
    re.IGNORECASE,
)


def is_douyin_media_url(url: str) -> bool:
    """Return whether *url* is a Douyin CDN video resource used by OriginalDoubao."""

    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and (hostname == "douyin.com" or hostname.endswith(".douyin.com"))
        and "/video/tos/" in parsed.path.lower()
    )


def is_supported_conversion_url(url: str) -> bool:
    """Accept OriginalDoubao share pages and their Douyin CDN video URLs."""

    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and (
            hostname in {"doubao.com", "www.doubao.com"}
            or is_douyin_media_url(url)
        )
    )


def force_no_watermark_url(url: str) -> str:
    """Apply the legacy rendition hint (not sufficient for encrypted fplay URLs)."""

    if re.search(r"([?&])lr=", url):
        return re.sub(r"([?&])lr=[^&]*", r"\1lr=video_gen_no_watermark", url)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}lr=video_gen_no_watermark"


def _base64_url_decode(value: str) -> bytes:
    normalized = value.replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    return base64.b64decode(normalized)


def _decode_fplay_url(value: str, key_seed: str) -> str:
    value = value.replace("&amp;", "&").strip()
    if value.startswith(("http://", "https://")):
        return value
    encrypted = _base64_url_decode(value)
    seed = _base64_url_decode(key_seed)
    ciphertext = encrypted[4:]
    if len(seed) < 32 or not ciphertext or len(ciphertext) % 16:
        return ""
    first_hash = hashlib.sha512(seed).digest()
    derived = hashlib.sha512(first_hash + _base64_url_decode(_FPLAY_KDF_SALT)).digest()
    decryptor = Cipher(algorithms.AES(derived[:16]), modes.CBC(derived[16:32])).decryptor()
    decrypted = decryptor.update(ciphertext) + decryptor.finalize()
    padding = decrypted[-1]
    if 1 <= padding <= 16 and decrypted.endswith(bytes([padding]) * padding):
        decrypted = decrypted[:-padding]
    return decrypted.decode("utf-8").strip()


def _clean_fplay_api_url(fallback_api: str) -> str:
    parsed = urlparse(fallback_api.replace("&amp;", "&"))
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
              if key not in {"force_fids", "logo_type", "codec_type"}]
    params.append(("codec_type", "1"))
    return urlunparse(parsed._replace(query=urlencode(params)))


async def original_doubao_fplay_parse(fallback_api: str, video_id: str) -> list[dict[str, object]]:
    """Resolve and decrypt an official OriginalDoubao fplay model URL."""

    clean_api = _clean_fplay_api_url(fallback_api)
    if not parse_qs(urlparse(clean_api).query).get("key_seed"):
        return []
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.doubao.com/",
        "User-Agent": "Mozilla/5.0",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(clean_api, headers=headers)
        response.raise_for_status()
        payload = response.json()
    data = payload.get("video_info", {}).get("data")
    if not isinstance(data, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload.get("video_info")
    if not isinstance(data, dict):
        return []
    key_seed = data.get("key_seed")
    video_list = data.get("video_list")
    if not isinstance(key_seed, str) or not isinstance(video_list, dict):
        return []
    videos: list[dict[str, object]] = []
    for definition, item in video_list.items():
        if not isinstance(item, dict) or str(item.get("logo_type") or "").strip():
            continue
        for field in ("main_url", "backup_url_1"):
            encoded_url = item.get(field)
            if not isinstance(encoded_url, str) or not encoded_url:
                continue
            try:
                media_url = _decode_fplay_url(encoded_url, key_seed)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
                continue
            if not media_url.startswith(("http://", "https://")) or "watermark" in media_url.lower():
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "url": media_url,
                    "width": item.get("vwidth") or item.get("width"),
                    "height": item.get("vheight") or item.get("height"),
                    "definition": item.get("definition") or definition,
                    "duration": data.get("duration") or item.get("duration"),
                    "poster_url": data.get("poster_url"),
                    "source": "fplay",
                }
            )
            break
    videos.sort(key=lambda video: int(video.get("width") or 0) * int(video.get("height") or 0), reverse=True)
    return videos


class OriginalDoubaoVideoEvidence:
    """Collect unique share links and video IDs from Playwright network evidence."""

    def __init__(self) -> None:
        self.share_urls: list[str] = []
        self.media_urls: list[str] = []
        self.video_ids: list[str] = []

    def add(self, value: object) -> None:
        if value is None:
            return
        text = str(value).replace(r"\/", "/").replace("&amp;", "&")
        for match in _SHARE_URL_PATTERN.findall(text):
            self._append_unique(self.share_urls, match.rstrip(".,);]"))
        for match in _MEDIA_URL_PATTERN.findall(text):
            self._append_unique(self.media_urls, match.rstrip(".,);]"))
        for pattern in _VIDEO_ID_PATTERNS:
            for match in pattern.findall(text):
                video_id = unquote(match).strip()
                if video_id and len(video_id) <= 256:
                    self._append_unique(self.video_ids, video_id)

    def parser_urls(self) -> list[str]:
        urls = list(reversed(self.share_urls))
        urls.extend(
            f"https://www.doubao.com/video-sharing?video_id={video_id}"
            for video_id in reversed(self.video_ids)
        )
        return list(dict.fromkeys(urls))

    def add_new_from(self, other: "OriginalDoubaoVideoEvidence", baseline: "OriginalDoubaoVideoEvidence") -> None:
        """Merge only evidence that was not present before this generation."""

        for share_url in other.share_urls:
            if share_url not in baseline.share_urls:
                self._append_unique(self.share_urls, share_url)
        for media_url in other.media_urls:
            if media_url not in baseline.media_urls:
                self._append_unique(self.media_urls, media_url)
        for video_id in other.video_ids:
            if video_id not in baseline.video_ids:
                self._append_unique(self.video_ids, video_id)

    @staticmethod
    def _append_unique(items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)


async def original_doubao_video_parse(
    url: str,
    cookies: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Resolve an OriginalDoubao share/thread URL to original, no-watermark media data."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"doubao.com", "www.doubao.com"}:
        raise ValueError("只支持 OriginalDoubao 官方分享链接")

    query_params = parse_qs(parsed.query)
    shared_video_ids = query_params.get("video_id", [])

    if "/thread/" in parsed.path:
        video_ids = await _get_thread_video_ids(url)
    else:
        video_ids = shared_video_ids
    if not video_ids:
        raise ValueError("链接中没有 video_id")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Origin": "https://www.doubao.com",
    }
    params = {
        "version_code": "20800",
        "language": "zh-CN",
        "device_platform": "web",
        "aid": "497858",
        "real_aid": "497858",
        "pkg_type": "release_version",
        "pc_version": "2.51.7",
        "samantha_web": "1",
        "use-olympus-account": "1",
        "web_tab_id": uuid.uuid4().hex,
    }
    videos: list[dict[str, object]] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as client:
        for video_id in _unique(video_ids):
            response = await client.post(
                "https://www.doubao.com/samantha/media/get_play_info",
                params=params,
                headers=headers,
                json={"key": video_id, "type": "video"},
            )
            response.raise_for_status()
            result = response.json()
            data = result.get("data")
            if not isinstance(data, dict):
                continue
            original = data.get("original_media_info")
            if not isinstance(original, dict) or not original.get("main_url"):
                continue
            meta = original.get("meta") if isinstance(original.get("meta"), dict) else {}
            videos.append(
                {
                    "video_id": video_id,
                    "url": str(original["main_url"]),
                    "width": meta.get("width"),
                    "height": meta.get("height"),
                    "definition": meta.get("definition"),
                    "duration": meta.get("duration"),
                    "poster_url": data.get("poster_url"),
                }
            )
    return videos


async def _get_thread_video_ids(url: str) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    return list(set(re.findall(r"{\\&quot;vid\\&quot;:\\&quot;(.*?)\\&quot", response.text)))


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
