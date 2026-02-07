"""Users API: GET list, POST, PATCH :id, DELETE :id. Доступ: только admin."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["users"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALLOWED_ROLES = ("admin", "hostess_1", "hostess_2")


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    display_name: str
    created_at: Optional[str]

    class Config:
        from_attributes = True


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: str
    display_name: str


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    display_name: Optional[str] = None


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> List[UserResponse]:
    """Список всех пользователей. Доступ: только admin."""
    result = await session.execute(select(User).order_by(User.id))
    users = result.scalars().all()
    return [
        UserResponse(
            id=u.id,
            email=u.email,
            role=u.role or "admin",
            display_name=u.display_name or u.email or "User",
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse)
async def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Создать пользователя. Доступ: только admin."""
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of: {', '.join(ALLOWED_ROLES)}",
        )
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalars().one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )
    raw = body.password.encode("utf-8")[:72]
    pwd_for_hash = raw.decode("utf-8", errors="ignore") or body.password[:1]
    user = User(
        email=body.email,
        password_hash=pwd_context.hash(pwd_for_hash),
        role=body.role,
        display_name=(body.display_name or body.email).strip() or "User",
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role or "admin",
        display_name=user.display_name or user.email or "User",
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Обновить пользователя. Доступ: только admin."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if body.email is not None:
        other = await session.execute(
            select(User).where(User.email == body.email, User.id != user_id)
        )
        if other.scalars().one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Another user with this email already exists",
            )
        user.email = body.email
    if body.display_name is not None:
        user.display_name = (body.display_name or user.email).strip() or "User"
    if body.role is not None:
        if body.role not in ALLOWED_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"role must be one of: {', '.join(ALLOWED_ROLES)}",
            )
        user.role = body.role
    if body.password is not None and body.password.strip():
        raw = body.password.encode("utf-8")[:72]
        pwd_for_hash = raw.decode("utf-8", errors="ignore") or body.password[:1]
        user.password_hash = pwd_context.hash(pwd_for_hash)
    await session.commit()
    await session.refresh(user)
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role or "admin",
        display_name=user.display_name or user.email or "User",
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_role(["admin"])),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Удалить пользователя. Нельзя удалить себя. Доступ: только admin."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await session.delete(user)
    await session.commit()
    return {"ok": True}
