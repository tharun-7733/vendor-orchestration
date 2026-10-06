from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.database import SessionLocal, engine
from app.auth import current_user, router as auth_router, verify_csrf
from app.models import Base, CaseStatus, ScreeningCase, User
from app.schemas import CaseResponse, ScreeningRequest
from app.worker import run_screening


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Convenient for local demos; production deployments should run versioned migrations.
    async with engine.begin() as connection:
        # Serialize the demo's startup DDL when serverless instances cold-start together.
        await connection.execute(text("SELECT pg_advisory_xact_lock(7241730049021)"))
        await connection.run_sync(Base.metadata.create_all)
        # Add per-user ownership to databases created by the earlier demo version.
        await connection.execute(
            text("ALTER TABLE screening_cases ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE")
        )
        await connection.execute(text("ALTER TYPE case_status ADD VALUE IF NOT EXISTS 'rejected'"))
        await connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_screening_cases_owner_id ON screening_cases (owner_id)")
        )
        # References are unique within an account; the prior demo enforced this globally.
        await connection.execute(text("DROP INDEX IF EXISTS ix_screening_cases_external_reference"))
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_screening_cases_owner_reference "
                "ON screening_cases (owner_id, external_reference)"
            )
        )
    yield
    await engine.dispose()


app = FastAPI(
    title="Vendor Orchestration API",
    version="0.1.0",
    description="Asynchronous KYC and sanctions screening with normalized case results.",
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory="public/assets"), name="assets")
app.include_router(auth_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith(("/auth/", "/v1/")):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/" or request.url.path.startswith("/assets/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
    return response


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse("public/index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/cases", response_model=CaseResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_case(
    request: ScreeningRequest,
    user: User = Depends(current_user),
    _: None = Depends(verify_csrf),
) -> CaseResponse:
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(ScreeningCase)
            .options(selectinload(ScreeningCase.results))
            .where(
                ScreeningCase.external_reference == request.external_reference,
                ScreeningCase.owner_id == user.id,
            )
        )
        if existing:
            if (
                existing.subject_name != request.subject_name
                or existing.date_of_birth != request.date_of_birth
                or existing.country != request.country
            ):
                raise HTTPException(
                    status_code=409,
                    detail="external_reference is already used for a different subject",
                )
            if existing.status == CaseStatus.failed:
                existing.status = CaseStatus.queued
                await session.commit()
                try:
                    run_screening.delay(str(existing.id))
                except Exception as exc:
                    existing.status = CaseStatus.failed
                    await session.commit()
                    raise HTTPException(
                        status_code=503,
                        detail="Screening queue is unavailable; retry later",
                    ) from exc
            return CaseResponse.model_validate(existing)
        case = ScreeningCase(**request.model_dump(), owner_id=user.id)
        session.add(case)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="external_reference already exists") from None
        await session.refresh(case)
        try:
            run_screening.delay(str(case.id))
        except Exception as exc:
            # Do not leave a case appearing queued when the broker rejected the dispatch.
            case.status = CaseStatus.failed
            await session.commit()
            raise HTTPException(status_code=503, detail="Screening queue is unavailable; retry later") from exc
        return CaseResponse.model_validate(case)


@app.get("/v1/cases", response_model=list[CaseResponse])
async def list_cases(
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
) -> list[CaseResponse]:
    async with SessionLocal() as session:
        cases = await session.scalars(
            select(ScreeningCase)
            .options(selectinload(ScreeningCase.results))
            .where(ScreeningCase.owner_id == user.id)
            .order_by(ScreeningCase.created_at.desc())
            .limit(limit)
        )
        return [CaseResponse.model_validate(case) for case in cases]


@app.get("/v1/cases/{case_id}", response_model=CaseResponse)
async def get_case(case_id: UUID, user: User = Depends(current_user)) -> CaseResponse:
    async with SessionLocal() as session:
        case = await session.scalar(
            select(ScreeningCase)
            .options(selectinload(ScreeningCase.results))
            .where(ScreeningCase.id == case_id, ScreeningCase.owner_id == user.id)
        )
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return CaseResponse.model_validate(case)
