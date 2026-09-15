"""飞书扫码 OAuth 设备码流程（手写 httpx，lark-oapi 不提供此流程）。

移植自 E:/FreeAgent/frontend-agent/internal/im/qr.go：
  1. POST {base}/oauth/v1/app/registration  action=init
  2. POST 同 URL  action=begin archetype=PersonalAgent auth_method=client_secret
     request_user_info=open_id  → 拿到 device_code + verification_uri_complete
  3. 在二维码 URL 挂 addons(from=sdk,tp=sdk) → segno 生成 PNG data URL
  4. 前端轮询 poll：POST 同 URL action=poll device_code=...
     → completed 时返回 client_id/client_secret/user_info.open_id/tenant_brand

注意：飞书 app/registration 在 pending / slow_down 等等待态会返回非 2xx（如 400），
但响应体仍是含 error 字段的合法 JSON，故不 raise_for_status，依据 body 内 error 判断状态。
"""
from __future__ import annotations

import base64
import gzip
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

# 扫码授权域名（accounts.*）与开放平台数据面域名（open.*）是两套，不可混用。
_ACCOUNTS_BASE = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}
_OPEN_BASE = {
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
}
_REGISTRATION_PATH = "/oauth/v1/app/registration"
_TIMEOUT = httpx.Timeout(35.0)

# 进程内扫码会话缓存：device_code -> {channel}。单进程 MVP 够用。
_scan_sessions: dict[str, dict] = {}


@dataclass
class ScanBeginResult:
    device_code: str
    verification_uri: str  # 二维码 data URL（image/png;base64）
    interval_sec: int = 3
    expire_in_sec: int = 600
    platform: str = "feishu"
    error: str = ""


@dataclass
class ScanPollResult:
    status: str  # pending | completed | denied | expired | error
    app_id: str = ""
    app_secret: str = ""
    owner_open_id: str = ""
    platform: str = "feishu"
    error: str = ""
    slow_down: bool = False
    interval_sec: int = 0


def _default_addons() -> dict:
    """长连接模式：订阅 im.message.receive_v1 事件 + 申请 im:message 权限。
    callbacks 留空（事件走 WebSocket 推送，无需公网回调地址）。"""
    return {
        "scopes": {"tenant": ["im:message"]},
        "events": {"items": {"tenant": ["im.message.receive_v1"]}},
    }


def _encode_addons(addons: dict) -> str:
    """json → gzip → urlsafe base64（去 = 填充），与飞书官方 SDK 编码一致。"""
    raw = json.dumps(addons, separators=(",", ":")).encode()
    gz = gzip.compress(raw)
    return base64.urlsafe_b64encode(gz).rstrip(b"=").decode()


def _append_query(url: str, params: dict) -> str:
    """在 URL 上追加 query 参数（自动用 ? 或 & 分隔，key/value 经 urlencode）。"""
    if not params:
        return url
    sep = "&" if ("?" in url) else "?"
    return url + sep + urlencode(params)


def _qr_data_uri(value: str) -> str:
    """用 segno 生成二维码 PNG data URL。"""
    import segno

    return segno.make(value, error="m").png_data_uri(scale=6)


def _post_registration(base: str, fields: dict) -> dict:
    """POST {base}/oauth/v1/app/registration，表单编码。

    不 raise_for_status：pending/slow_down 返 400 但 body 仍是合法 JSON，靠 error 字段判状态。
    """
    try:
        with httpx.Client(timeout=_TIMEOUT) as c:
            r = c.post(base + _REGISTRATION_PATH, data=fields)
            return r.json()
    except Exception as exc:  # noqa: BLE001 - 网络层异常归一化为 error
        return {"error": "request_failed", "error_description": str(exc)[:200]}


def scan_begin(channel: str = "feishu") -> ScanBeginResult:
    """发起扫码：init → begin，返回二维码 data URL 与 device_code。"""
    base = _ACCOUNTS_BASE.get(channel, _ACCOUNTS_BASE["feishu"])

    # 1) init
    d = _post_registration(base, {"action": "init"})
    if d.get("error"):
        return ScanBeginResult(device_code="", verification_uri="", platform=channel, error=d["error"])

    # 2) begin：声明 PersonalAgent 原型 + client_secret 方式
    d = _post_registration(base, {
        "action": "begin",
        "archetype": "PersonalAgent",
        "auth_method": "client_secret",
        "request_user_info": "open_id",
    })
    if d.get("error"):
        return ScanBeginResult(device_code="", verification_uri="", platform=channel, error=d["error"])

    device_code = d.get("device_code", "")
    raw_uri = d.get("verification_uri_complete", "")
    if not device_code or not raw_uri:
        return ScanBeginResult(
            device_code="", verification_uri="", platform=channel, error="missing_device_code",
        )
    interval = int(d.get("interval") or 3)
    expire_in = int(d.get("expire_in") or 600)

    # 3) 挂载 addons + from + tp，生成二维码
    uri = _append_query(raw_uri, {
        "addons": _encode_addons(_default_addons()),
        "from": "sdk",
        "tp": "sdk",
    })
    qr = _qr_data_uri(uri)
    _scan_sessions[device_code] = {"channel": channel}
    return ScanBeginResult(
        device_code=device_code, verification_uri=qr,
        interval_sec=max(2, interval), expire_in_sec=expire_in, platform=channel,
    )


def scan_poll(channel: str, device_code: str) -> ScanPollResult:
    """轮询扫码状态：用户扫码确认后开放平台返回 client_id/client_secret。"""
    base = _ACCOUNTS_BASE.get(channel, _ACCOUNTS_BASE["feishu"])
    # lark 域名自动切换：用户用 Lark App 扫了 feishu 域名的码时，按 tenant_brand 切到 lark 域名重试一次。
    for attempt in range(2):
        d = _post_registration(base, {"action": "poll", "device_code": device_code})
        user_info = d.get("user_info") or {}
        brand = user_info.get("tenant_brand") or ""

        # 仅当确认是 lark 且当前不是 lark 域名时切换（pending 时 user_info 为空，不会触发）
        if brand == "lark" and base != _ACCOUNTS_BASE["lark"] and attempt == 0:
            base = _ACCOUNTS_BASE["lark"]
            continue

        app_id = d.get("client_id", "")
        app_secret = d.get("client_secret", "")
        owner = user_info.get("open_id", "")

        if app_id and app_secret:
            platform = "lark" if brand == "lark" else ("feishu" if brand == "feishu" else channel)
            return ScanPollResult(
                status="completed", app_id=app_id, app_secret=app_secret,
                owner_open_id=owner, platform=platform,
            )

        err = d.get("error", "")
        interval = int(d.get("interval") or 3)
        if err == "slow_down":
            return ScanPollResult(status="pending", slow_down=True, platform=channel, interval_sec=interval)
        if err in ("", "authorization_pending"):
            return ScanPollResult(status="pending", platform=channel)
        if err == "access_denied":
            return ScanPollResult(status="denied", error="授权被拒绝", platform=channel)
        if err == "expired_token":
            return ScanPollResult(status="expired", error="二维码已过期", platform=channel)
        return ScanPollResult(status="error", error=err or "unknown", platform=channel)

    return ScanPollResult(status="error", error="retry_exhausted", platform=channel)


def open_base(channel: str) -> str:
    """开放平台数据面域名（发消息 / 取 token 用）。"""
    return _OPEN_BASE.get(channel, _OPEN_BASE["feishu"])
