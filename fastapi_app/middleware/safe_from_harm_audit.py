from __future__ import annotations

import json
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fastapi_app.db_bridge import create_audit_log_entry


class SafeFromHarmAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method != "POST" or request.url.path != "/validation/seed":
            return await call_next(request)

        body_bytes = await request.body()

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        replay_request = Request(request.scope, receive)
        response = await call_next(replay_request)

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        parsed_request = self._try_parse_json(body_bytes)
        parsed_response = self._try_parse_json(response_body)

        input_text = str(parsed_request.get("text") or "")
        flagged_status = bool(parsed_response.get("flagged"))

        user_identifier = (
            str(parsed_request.get("user") or "")
            or str(parsed_request.get("user_id") or "")
            or str(parsed_request.get("telegram_chat_id") or "")
            or request.headers.get("x-user-id", "")
            or request.headers.get("x-telegram-chat-id", "")
        )

        await run_in_threadpool(
            create_audit_log_entry,
            user_identifier=user_identifier,
            input_text=input_text,
            ai_response=parsed_response,
            flagged_status=flagged_status,
        )

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    @staticmethod
    def _try_parse_json(payload: bytes) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            parsed = json.loads(payload.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
