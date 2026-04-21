from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from fastapi_app.services.gemini_seed_validator import DEFAULT_MODEL, validate_esperanto_content

router = APIRouter(prefix="/validation", tags=["validation"])


class SeedValidationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=4000)
    model: str = DEFAULT_MODEL
    max_retries: int = Field(default=3, ge=1, le=5)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    timeout_seconds: int = Field(default=60, ge=5, le=120)


class SeedValidationResponse(BaseModel):
    flagged: bool
    comprehensible: bool
    encouragement_message: str


@router.post("/seed", response_model=SeedValidationResponse)
async def validate_seed_content(payload: SeedValidationRequest) -> SeedValidationResponse:
    try:
        result = await run_in_threadpool(
            validate_esperanto_content,
            payload.text,
            model=payload.model,
            max_retries=payload.max_retries,
            temperature=payload.temperature,
            timeout_seconds=payload.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return SeedValidationResponse(**result)
