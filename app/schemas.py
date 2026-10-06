from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class ScreeningRequest(BaseModel):
    external_reference: str = Field(min_length=1, max_length=128)
    subject_name: str = Field(min_length=1, max_length=200)
    date_of_birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    country: str = Field(default="IN", min_length=2, max_length=2)

    @field_validator("external_reference", "subject_name")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized != "IN":
            raise ValueError("This demonstration supports India only")
        return normalized


class VendorResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    vendor: str
    outcome: str
    matched: bool
    confidence: float | None
    payload: dict
    error: str | None
    created_at: datetime


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    external_reference: str
    subject_name: str
    date_of_birth: str | None
    country: str | None
    status: str
    attempts: int
    created_at: datetime
    updated_at: datetime
    results: list[VendorResultResponse] = []

    @computed_field
    @property
    def decision(self) -> str:
        results = {result.vendor: result for result in self.results}
        kyc = results.get("kyc")
        sanctions = results.get("sanctions")
        if self.status in {"queued", "processing", "failed"} or not kyc or not sanctions:
            return "PENDING"
        if kyc.error or sanctions.error:
            return "PENDING"
        if sanctions.outcome == "review":
            return "NEEDS_REVIEW"
        if kyc.outcome == "failed":
            return "REJECTED"
        if kyc.outcome == "clear" and sanctions.outcome == "clear":
            return "CLEARED"
        return "PENDING"

    @computed_field
    @property
    def reason(self) -> str:
        decision = self.decision
        return {
            "CLEARED": "Identity verification passed and sanctions screening returned no match.",
            "NEEDS_REVIEW": "A possible sanctions match needs human review; it is not a confirmed match.",
            "REJECTED": "Identity verification failed.",
            "PENDING": "Required provider results are pending or unavailable.",
        }[decision]

    @computed_field
    @property
    def review_required(self) -> bool:
        return self.decision == "NEEDS_REVIEW"

    @computed_field
    @property
    def confidence(self) -> float | None:
        results = {result.vendor: result for result in self.results}
        if self.decision == "NEEDS_REVIEW":
            return results["sanctions"].confidence
        if self.decision == "REJECTED":
            return results["kyc"].confidence
        if self.decision == "CLEARED":
            scores = [results[name].confidence for name in ("kyc", "sanctions")]
            available = [score for score in scores if score is not None]
            return min(available) if available else None
        return None
