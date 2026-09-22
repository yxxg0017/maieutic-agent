"""启动期 token 认证与 Origin/Host 校验。"""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, status

ALLOWED_HOSTS = ("127.0.0.1", "localhost")


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
            if hostname not in ALLOWED_HOSTS and not origin.startswith("tauri://"):
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
