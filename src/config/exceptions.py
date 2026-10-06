"""配置域异常"""

from __future__ import annotations


class SettingsValidationError(ValueError):
    """2026-09-10 设置保存校验失败（配置解析快速失败 / .env 白名单违规 / 凭据组合不完整）"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
