import asyncio
import hashlib
import hmac
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models import User

router = APIRouter(prefix="/auth", tags=["authentication"])
signing_secret = settings.session_secret or secrets.token_urlsafe(48)
serializer = URLSafeTimedSerializer(signing_secret, salt="vendor-orchestration-session-v1")
csrf_serializer = URLSafeTimedSerializer(signing_secret, salt="vendor-orchestration-csrf-v1")
SESSION_COOKIE = "vo_session"
CSRF_COOKIE = "vo_csrf"
PBKDF2_ITERATIONS = 600_000


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or any(char.isspace() for char in value):
            raise ValueError("Enter a valid email address")
        local, _, domain = value.partition("@")
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Enter a valid email address")
        return value


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str


async def verify_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF validation failed. Refresh and retry.")
    try:
        csrf_serializer.loads(cookie_token, max_age=settings.session_ttl_seconds)
    except BadSignature:
        raise HTTPException(status_code=403, detail="CSRF token is invalid or expired. Refresh and retry.") from None


async def current_user(request: Request) -> User:
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    try:
        user_id = uuid.UUID(serializer.loads(session_token, max_age=settings.session_ttl_seconds))
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.") from None
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to continue")
        return user


def set_session_cookies(response: Response, user_id: uuid.UUID, csrf_token: str) -> None:
    cookie_options = {
        "secure": settings.session_cookie_secure,
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(
        SESSION_COOKIE,
        serializer.dumps(str(user_id)),
        max_age=settings.session_ttl_seconds,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        **cookie_options,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(iterations) != PBKDF2_ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


@router.get("/csrf")
async def csrf_token(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(CSRF_COOKIE)
    if token:
        try:
            csrf_serializer.loads(token, max_age=settings.session_ttl_seconds)
        except BadSignature:
            token = None
    if not token:
        token = csrf_serializer.dumps(secrets.token_urlsafe(32))
        response.set_cookie(
            CSRF_COOKIE,
            token,
            max_age=settings.session_ttl_seconds,
            httponly=False,
            secure=settings.session_cookie_secure,
            samesite="strict",
            path="/",
        )
    return {"csrf_token": token}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    credentials: Credentials,
    response: Response,
    request: Request,
    _: None = Depends(verify_csrf),
) -> UserResponse:
    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.email == credentials.email))
        if existing:
            raise HTTPException(status_code=409, detail="An account with that email already exists")
        user = User(
            email=credentials.email,
            password_hash=await asyncio.to_thread(hash_password, credentials.password),
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Could not create account with that email") from None
        await session.refresh(user)
        set_session_cookies(response, user.id, request.cookies[CSRF_COOKIE])
        return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=UserResponse)
async def login(
    credentials: Credentials,
    response: Response,
    request: Request,
    _: None = Depends(verify_csrf),
) -> UserResponse:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == credentials.email))
        stored = user.password_hash if user else "pbkdf2_sha256$600000$00000000000000000000000000000000$" + "0" * 64
        valid = await asyncio.to_thread(check_password, credentials.password, stored)
        if not user or not valid:
            raise HTTPException(status_code=401, detail="Email or password is incorrect")
        set_session_cookies(response, user.id, request.cookies[CSRF_COOKIE])
        return UserResponse(id=user.id, email=user.email)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(current_user)) -> UserResponse:
    return UserResponse(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    _: User = Depends(current_user),
    __: None = Depends(verify_csrf),
) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.session_cookie_secure, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.session_cookie_secure, samesite="strict")
    return response
