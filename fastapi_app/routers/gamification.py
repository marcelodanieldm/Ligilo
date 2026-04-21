from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from fastapi_app.services.patrol_service import get_certification_qr_payload

router = APIRouter(prefix="/gamification", tags=["gamification"])


class CertificationQRResponse(BaseModel):
    eligible: bool
    current_points: int | None = None
    required_points: int | None = None
    qr_url: str | None = None
    payload: dict | None = None


@router.get("/patrols/{patrol_id}/certification-qr", response_model=CertificationQRResponse)
async def certification_qr(patrol_id: int) -> CertificationQRResponse:
    result = await get_certification_qr_payload(patrol_id)
    if not result.get("eligible"):
        reason = result.get("reason")
        if reason == "patrol_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patrol not found")
        if reason == "insufficient_points":
            return CertificationQRResponse(
                eligible=False,
                current_points=result.get("current_points"),
                required_points=result.get("required_points"),
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to generate certification QR")

    return CertificationQRResponse(
        eligible=True,
        qr_url=result.get("qr_url"),
        payload=result.get("payload"),
    )
