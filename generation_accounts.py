"""生成账号的平台信息；历史未标类型的账号属于豆包。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from constants import ORIGINAL_DOUBAO_URL


ACCOUNT_PLATFORMS = {
    "doubao": {"label": "OriginaDoubao", "url": ORIGINAL_DOUBAO_URL, "domain": "doubao.com"},
    "dola": {"label": "Dola", "url": "https://www.dola.com/chat", "domain": "dola.com"},
}


def normalize_account_type(value: Any = "") -> str:
    account_type = str(value or "doubao").strip().lower()
    if account_type not in ACCOUNT_PLATFORMS:
        raise ValueError("不支持的账号类型，请选择 OriginaDoubao 或 Dola")
    return account_type


def account_platform(account: dict[str, Any]) -> dict[str, str]:
    return ACCOUNT_PLATFORMS[normalize_account_type(account.get("accountType"))]


def is_platform_url(url: str, domain: str) -> bool:
    parsed = urlparse(str(url or ""))
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (hostname == domain or hostname.endswith("." + domain))
