"""Shared API dependencies: DB session and authentication."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import User
from app.core.security import verify_token


def current_user(db: Session = Depends(get_db), authorization: str | None = Header(default=None),
                 token: str | None = Query(default=None, description="for EventSource/downloads")) -> User:
    s = get_settings()
    if not s.auth_enabled:
        user = db.scalar(select(User).where(User.username == s.admin_username))
        if user is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no admin user seeded")
        return user
    raw = token
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    username = verify_token(raw) if raw else None
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token", headers={"WWW-Authenticate": "Bearer"})
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return user
