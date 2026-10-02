"""Доменные исключения сервиса.

Роутеры переводят их в HTTP-коды (единственное место, где сервис «знает» про HTTP —
ничего; маппинг живёт в api-слое). Это позволяет слоям сервисов не зависеть от FastAPI.
"""
from __future__ import annotations



class DomainError(Exception):
    """Базовое доменное нарушение инвариантов."""


class NotFoundError(DomainError):
    """Сущность не найдена (→ 404)."""


class ConflictError(DomainError):
    """Нарушение уникальности/состояния (→ 409)."""


class ValidationError(DomainError):
    """Некорректные входные данные на уровне бизнес-правил (→ 400)."""


class UnauthorizedError(DomainError):
    """Аутентификация не пройдена / токен недействителен (→ 401)."""


class ForbiddenError(DomainError):
    """Аутентифицирован, но прав недостаточно (→ 403)."""
