import asyncio
from typing import Any


class MockKYCProvider:
    """Deterministic KYC sandbox: names containing 'unverified' produce a failed check."""

    name = "mock_kyc"

    async def check(self, subject: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.15)
        verified = "unverified" not in subject["subject_name"].lower()
        return {
            "provider": self.name,
            "verification": "verified" if verified else "unverified",
            "identity_match": verified,
            "score": 0.98 if verified else 0.21,
            "reference": f"kyc-{subject['external_reference']}",
        }


class MockSanctionsProvider:
    """Deterministic sanctions sandbox: names containing 'sanction' return a hit."""

    name = "mock_sanctions"

    async def check(self, subject: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.15)
        hit = "sanction" in subject["subject_name"].lower()
        return {
            "provider": self.name,
            "screening_status": "potential_match" if hit else "no_match",
            "hits": [{"list": "DEMO-IN-MOCK-LIST", "score": 0.91}] if hit else [],
        }
