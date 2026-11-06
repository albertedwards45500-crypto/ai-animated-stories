# -*- coding: utf-8 -*-
"""统一响应格式与错误码定义。

所有 REST 接口返回 ``{"code": 0, "message": "ok", "data": {...}}`` 结构；
错误码与 HTTP 状态映射依据《API接口文档.md》第 1 节。
"""
from typing import Any

from fastapi import responses

# ---- 错误码 ----
CODE_OK = 0
CODE_PARAM_INVALID = 40001       # 参数校验失败
CODE_BIZ_INVALID = 40002         # 业务校验失败
CODE_NOT_FOUND = 40401           # 资源不存在
CODE_STATE_CONFLICT = 40901      # 状态冲突
CODE_QUOTA_EXCEEDED = 42901      # 超出 Provider 每日额度
CODE_INTERNAL = 50001            # 服务器内部错误
CODE_UPSTREAM_ERROR = 50201      # 上游 AI 供应商错误
CODE_UNAVAILABLE = 50301         # 本地依赖未就绪
CODE_UPSTREAM_TIMEOUT = 50401    # 上游超时

# 错误码 → HTTP 状态码
HTTP_STATUS_MAP: dict[int, int] = {
    CODE_OK: 200,
    CODE_PARAM_INVALID: 400,
    CODE_BIZ_INVALID: 400,
    CODE_NOT_FOUND: 404,
    CODE_STATE_CONFLICT: 409,
    CODE_QUOTA_EXCEEDED: 429,
    CODE_INTERNAL: 500,
    CODE_UPSTREAM_ERROR: 502,
    CODE_UNAVAILABLE: 503,
    CODE_UPSTREAM_TIMEOUT: 504,
}


class BizError(Exception):
    """业务异常。

    路由层与服务层通过抛出该异常返回统一错误响应，
    由全局异常处理器转换为 ``{code, message, data}``。

    Attributes:
        code: 业务错误码（见本模块常量）。
        message: 人类可读错误信息。
        data: 附加错误详情（如字段级错误列表）。
    """

    def __init__(self, code: int, message: str, data: Any = None):
        """初始化业务异常。

        Args:
            code: 业务错误码。
            message: 错误信息。
            data: 附加详情，默认 None。
        """
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

    @property
    def http_status(self) -> int:
        """获取对应的 HTTP 状态码。

        Returns:
            int: HTTP 状态码，未知错误码按 500 处理。
        """
        return HTTP_STATUS_MAP.get(self.code, 500)


def ok(data: Any = None, message: str = "ok") -> responses.JSONResponse:
    """构造统一成功响应。

    Args:
        data: 业务数据。
        message: 提示信息，默认 "ok"。

    Returns:
        responses.JSONResponse: ``{"code": 0, "message": ..., "data": ...}``。
    """
    return responses.JSONResponse({"code": CODE_OK, "message": message, "data": data})


def fail(code: int, message: str, data: Any = None) -> responses.JSONResponse:
    """构造统一失败响应。

    Args:
        code: 业务错误码。
        message: 错误信息。
        data: 附加详情，默认 None。

    Returns:
        responses.JSONResponse: 统一错误结构。
    """
    return responses.JSONResponse(
        {"code": code, "message": message, "data": data},
        status_code=HTTP_STATUS_MAP.get(code, 500),
    )
