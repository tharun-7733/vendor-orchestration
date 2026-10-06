import asyncio
from uuid import UUID

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.config import settings
from app.models import CaseStatus, ScreeningCase, VendorResult
from app.normalization import normalize_kyc, normalize_sanctions
from app.providers import MockKYCProvider, MockSanctionsProvider
from app.queue import celery_app


async def _screen(case_id: UUID) -> None:
    async with SessionLocal() as session:
        case = await session.scalar(select(ScreeningCase).where(ScreeningCase.id == case_id))
        if case is None:
            return
        case.status = CaseStatus.processing
        case.attempts += 1
        subject = {
            "external_reference": case.external_reference,
            "subject_name": case.subject_name,
            "date_of_birth": case.date_of_birth,
            "country": case.country,
        }
        await session.commit()

        kyc, sanctions = await asyncio.gather(
            MockKYCProvider().check(subject), MockSanctionsProvider().check(subject)
        )
        results = [normalize_kyc(kyc), normalize_sanctions(sanctions)]
        await session.execute(delete(VendorResult).where(VendorResult.case_id == case_id))
        for result in results:
            session.add(VendorResult(case_id=case_id, **result))
        case = await session.scalar(select(ScreeningCase).where(ScreeningCase.id == case_id))
        by_vendor = {result["vendor"]: result for result in results}
        if any(result["error"] for result in results):
            case.status = CaseStatus.failed
        elif by_vendor["sanctions"]["outcome"] == "review":
            case.status = CaseStatus.review
        elif by_vendor["kyc"]["outcome"] == "failed":
            case.status = CaseStatus.rejected
        elif all(result["outcome"] == "clear" for result in results):
            case.status = CaseStatus.clear
        else:
            case.status = CaseStatus.failed
        await session.commit()


@celery_app.task(bind=True, name="screening.run", max_retries=settings.max_retries)
def run_screening(self, case_id: str) -> None:
    try:
        asyncio.run(_screen(UUID(case_id)))
    except Exception as exc:
        if self.request.retries >= settings.max_retries:
            asyncio.run(_mark_failed(UUID(case_id)))
            raise
        countdown = settings.retry_base_seconds * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown, max_retries=settings.max_retries)


async def _mark_failed(case_id: UUID) -> None:
    async with SessionLocal() as session:
        case = await session.scalar(select(ScreeningCase).where(ScreeningCase.id == case_id))
        if case is not None:
            case.status = CaseStatus.failed
            await session.commit()
