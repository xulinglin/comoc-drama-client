"""Official OriginalDoubao and Dola no-watermark video parsing helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse
from urllib.request import getproxies

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
    """Accept Doubao/Dola share pages and their platform CDN video URLs."""

    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and (
            hostname in {"doubao.com", "www.doubao.com", "dola.com", "www.dola.com"}
            or is_douyin_media_url(url)
            or is_dola_media_url(url)
        )
    )


def is_dola_media_url(url: str) -> bool:
    parsed = urlparse(str(url).strip())
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and re.fullmatch(r"v\d+(?:-[a-z0-9-]+)?\.dola\.com", hostname) is not None
        and "/video/tos/" in parsed.path.lower()
    )


def conversion_account_type(url: str) -> str:
    if not is_supported_conversion_url(url):
        return ""
    hostname = (urlparse(str(url).strip()).hostname or "").lower()
    return "dola" if hostname in {"dola.com", "www.dola.com"} or is_dola_media_url(url) else "doubao"


def platform_media_proxy(referer: str) -> str | None:
    """Follow the Windows system proxy for international media requests."""
    if (urlparse(referer).hostname or "").lower() not in {"dola.com", "www.dola.com"}:
        return None
    proxies = getproxies()
    return proxies.get("https") or proxies.get("http") or None


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


async def dola_video_parse(
    video_ids: Iterable[str], cookies: dict[str, str], *, proxy: str | None = None,
) -> list[dict[str, object]]:
    """Use Dola's official AI-watermark setting and original-download endpoint."""
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return []
    jar = httpx.Cookies()
    for name, value in cookies.items():
        jar.set(name, value, domain=".dola.com", path="/")
    params = {"aid": "495671", "real_aid": "495671", "device_platform": "web", "language": "en", "samantha_web": "1"}
    headers = {"Origin": "https://www.dola.com", "Referer": "https://www.dola.com/chat", "User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=jar, proxy=proxy) as client:
        async def request(path: str, body: dict[str, object]) -> dict[str, object]:
            response = await client.post("https://www.dola.com" + path, params=params, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
            code = int(payload.get("code") or 0)
            if code == 710012001:
                raise ValueError("Dola 账号登录已过期，请重新登录")
            if code == 710022003:
                raise ValueError("Dola 当前网络受地区限制，请检查账号浏览器使用的网络")
            if code:
                raise ValueError(str(payload.get("msg") or payload.get("message") or f"Dola 接口错误 {code}"))
            data = payload.get("data")
            return data if isinstance(data, dict) else {}

        resource_path = "/creativity/resource/get_without_watermark"
        data = await request(resource_path, {"vid": ids})
        enabled_here = False
        if data.get("without_watermark") is False:
            config = await request("/creativity/user_config/get", {})
            option = config.get("config_map", {}).get("1", {}).get("watermark_option", {})
            if (option.get("subscribe_config") or {}).get("need_upgrade") is True:
                raise ValueError("Dola 官方提示当前账号需升级才能使用去 AI 水印功能")
            if option.get("is_on") is True:
                raise ValueError("Dola 去 AI 水印开关已开启，但官方未提供该视频的无水印资源")
            await request("/creativity/user_config/set", {"config_type": 1, "config_value": {"watermark_option": {"is_on": True}}})
            enabled_here = True
        try:
            if enabled_here:
                data = await request(resource_path, {"vid": ids})
            if data.get("without_watermark") is not True:
                raise ValueError("Dola 官方未提供该视频的无水印资源，请检查账号功能权限或视频状态")
            videos = []
            downloads = data.get("download_video") or {}
            for video_id in ids:
                item = downloads.get(video_id) if isinstance(downloads, dict) else None
                if not isinstance(item, dict):
                    continue
                url = item.get("download_url")
                if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
                    continue
                videos.append({"video_id": video_id, "url": url, "duration": item.get("duration"), "source": "dola_official_without_watermark"})
            if not videos:
                raise ValueError("Dola 官方无水印接口未返回该视频的下载地址")
            return videos
        except Exception:
            if enabled_here:
                # Restore the user's previous setting if enabling did not yield a result.
                try:
                    await request("/creativity/user_config/set", {"config_type": 1, "config_value": {"watermark_option": {"is_on": False}}})
                except Exception:
                    pass
            raise


async def original_doubao_fplay_parse(
    fallback_api: str, video_id: str, *, referer: str = "https://www.doubao.com/", proxy: str | None = None,
) -> list[dict[str, object]]:
    """Resolve and decrypt an official OriginalDoubao fplay model URL."""

    clean_api = _clean_fplay_api_url(fallback_api)
    if not parse_qs(urlparse(clean_api).query).get("key_seed"):
        return []
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "User-Agent": "Mozilla/5.0",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, proxy=proxy) as client:
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
