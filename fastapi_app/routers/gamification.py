from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from fastapi_app.db_bridge import build_weekly_report_for_patrol
from fastapi_app.services.patrol_service import get_certification_qr_payload

router = APIRouter(prefix="/gamification", tags=["gamification"])


class CertificationQRResponse(BaseModel):
    eligible: bool
    tier: str | None = None
    current_points: int | None = None
    required_points: int | None = None
    certification_code: str | None = None
    profile_url: str | None = None
    qr_url: str | None = None
    qr_png_b64: str | None = None
    payload: dict | None = None
    renewed: bool = False


class WeeklyReportResponse(BaseModel):
    patrol_name: str
    delegation_name: str
    leader_name: str
    period_start: str
    period_end: str
    texts_validated: int
    audios_validated: int
    youtube_missions: int
    consistency_bonuses: int
    weekly_points: int
    total_sel_points: int
    estimated_words_learned: int
    summary_message: str


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
        tier=result.get("tier"),
        certification_code=result.get("certification_code"),
        profile_url=result.get("profile_url"),
        qr_url=result.get("qr_url"),
        qr_png_b64=result.get("qr_png_b64"),
        payload=result.get("payload"),
        renewed=result.get("renewed", False),
    )


@router.get("/patrol/weekly-report/{chat_id}", response_model=WeeklyReportResponse)
async def weekly_report(chat_id: int) -> WeeklyReportResponse:
    """Weekly learning report for a patrol leader, identified by Telegram chat_id."""
    result = await build_weekly_report_for_patrol(chat_id)
    if not result.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patrol not found")
    return WeeklyReportResponse(**{k: v for k, v in result.items() if k != "success"})
