"""Маскирование чувствительных значений в логах."""

from typing import Final

MASK: Final = "***"


def mask_email(value: str) -> str:
    """Замаскировать локальную часть email для логов.

    Домен сохраняется, чтобы можно было отличить провайдера или корпоративный
    почтовый домен. Локальная часть сокращается до первой буквы.
    """
    local, separator, domain = value.strip().partition("@")
    if not separator or not local or not domain:
        return MASK
    masked_local = MASK if len(local) == 1 else f"{local[0]}{MASK}"
    return f"{masked_local}@{domain}"
