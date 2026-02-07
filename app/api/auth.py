"""POST /api/auth/login: email/password → JWT и user (id, email, role, display_name)."""
import logging
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User
from app.db.session import get_session

logger = logging.getLogger(__name__)

_settings = Settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    display_name: str


class LoginResponse(BaseModel):
    access_token: str
    user: UserResponse


def _create_access_token(user_id: int) -> str:
    if not (_settings.jwt_secret and _settings.jwt_secret.strip()):
        raise ValueError("JWT_SECRET is not set")
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    # PyJWT требует exp как число (Unix timestamp), не datetime
    payload = {"sub": str(user_id), "exp": int(expire.timestamp())}
    token = jwt.encode(
        payload,
        _settings.jwt_secret,
        algorithm=_settings.jwt_algorithm,
    )
    return token if isinstance(token, str) else token.decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    """Проверка пароля; при ошибке passlib (битый хеш) — считаем неверным."""
    try:
        return bool(hashed and pwd_context.verify(plain, hashed))
    except Exception:
        return False


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    """Проверка email/password по users; возврат JWT и данные user."""
    try:
        result = await session.execute(
            select(User).where(User.email == body.email)
        )
        user = result.scalars().one_or_none()
        if not user or not _verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        access_token = _create_access_token(user.id)
        return LoginResponse(
            access_token=access_token,
            user=UserResponse(
                id=user.id,
                email=user.email,
                role=user.role or "admin",
                display_name=user.display_name or user.email or "User",
            ),
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.exception("Login config error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        ) from e
    except Exception as e:
        logger.exception("Login failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed. Please try again.",
        ) from e
