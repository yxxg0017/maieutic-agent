"""启动期 token 认证与 Origin/Host 校验。"""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, status

ALLOWED_HOSTS = ("127.0.0.1", "localhost")
# WKWebView 从 tauri://localhost 发起的明文 http 请求会被当作混合内容拦截，因此
# 桌面壳使用 http scheme（http://tauri.localhost），这里必须放行该来源。
ALLOWED_ORIGIN_HOSTS = (*ALLOWED_HOSTS, "tauri.localhost")

# 桌面壳可能出现的来源：macOS/Linux 的自定义协议、Windows/Android 的 http scheme、
# 以及开发模式下的 Vite 服务器。带 Authorization 头的请求会触发 CORS 预检，
# 没有匹配的 Access-Control-Allow-Origin 时 webview 会直接拒绝请求。
DESKTOP_ORIGIN_REGEX = (
    r"^(tauri|asset)://localhost$"
    r"|^https?://tauri\.localhost$"
    r"|^https?://(127\.0\.0\.1|localhost)(:\d+)?$"
)


def new_session_token() -> str:
    """256-bit 随机 token。每次启动重新生成，不落盘。"""
    return secrets.token_urlsafe(32)


class TokenGuard:
    def __init__(self, token: str) -> None:
        self._token = token

    def _check_token(self, request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value, self._token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session_token"
            )

    def _check_origin(self, request: Request) -> None:
        host = (request.headers.get("host") or "").split(":")[0]
        if host and host not in ALLOWED_HOSTS:
            raise HTTPException(status_code=403, detail="host_not_allowed")
        origin = request.headers.get("origin")
        if origin:
            hostname = origin.split("//", 1)[-1].split(":")[0]
            if hostname not in ALLOWED_ORIGIN_HOSTS and not origin.startswith("tauri://"):
                raise HTTPException(status_code=403, detail="origin_not_allowed")

    async def __call__(self, request: Request) -> None:
        self._check_origin(request)
        self._check_token(request)


def redact(text: str, *secrets_to_remove: str) -> str:
    """从错误信息或导出内容中剔除密钥与绝对路径。"""
    result = text
    for value in secrets_to_remove:
        if value:
            result = result.replace(value, "***")
    return result
