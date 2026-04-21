from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi_app.database import get_db
from fastapi_app.middleware.safe_from_harm_audit import SafeFromHarmAuditMiddleware
from fastapi_app.routers.validation import router as validation_router
from fastapi_app.routers.webhooks import router as webhook_router
from fastapi_app.services.telegram_bot import init_telegram_application

app = FastAPI(title="Ligilo Webhooks API", version="0.1.0")
app.add_middleware(SafeFromHarmAuditMiddleware)
app.include_router(webhook_router)
app.include_router(validation_router)


@app.on_event("startup")
async def startup_telegram() -> None:
    try:
        await init_telegram_application()
    except RuntimeError:
        # La API restas operacia eĉ se la boto ne estas agordita ankoraŭ.
        pass


@app.get("/health", tags=["health"])
def healthcheck(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
