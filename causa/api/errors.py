"""
errors.py — translates exceptions raised by the real Step 1-9 engines into
HTTP responses. Never invents a new error taxonomy: every case here maps a
real, already-documented exception type (DriverRequestError,
UnauthorizedSegmentError, UnsupportedFilterError, ReconciliationError,
BudgetExceeded, InvalidFeedbackError, ...) to an HTTP status, and redacts the
message via evidence.access_control.redact_error_message before it leaves
the process (never leaks an identifier-shaped token to a sub-INTERNAL
caller).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evidence.access_control import redact_error_message


def _envelope(status: int, error_type: str, message: str, clearance: str = "PUBLIC_ANALYTICAL") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": redact_error_message(message, clearance)}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    from drivers.engine import DriverRequestError, ReconciliationError, UnauthorizedSegmentError, UnsupportedSegmentError
    from evidence.retrieval import UnauthorizedFilterError, UnsupportedFilterError
    from kpi.query_planner import KPIRequestError
    from agents.models import BudgetExceeded
    from agents.state_machine import InvalidTransitionError
    from feedback.models import InvalidFeedbackError
    from feedback.review import ReviewError

    def _clearance(request: Request) -> str:
        return getattr(request.state, "requester_clearance", "PUBLIC_ANALYTICAL")

    @app.exception_handler(UnauthorizedSegmentError)
    @app.exception_handler(UnauthorizedFilterError)
    @app.exception_handler(PermissionError)
    async def _forbidden(request: Request, exc: Exception):
        return _envelope(403, type(exc).__name__, str(exc), _clearance(request))

    @app.exception_handler(UnsupportedSegmentError)
    @app.exception_handler(UnsupportedFilterError)
    @app.exception_handler(KPIRequestError)
    @app.exception_handler(InvalidFeedbackError)
    @app.exception_handler(ValueError)
    async def _bad_request(request: Request, exc: Exception):
        return _envelope(400, type(exc).__name__, str(exc), _clearance(request))

    @app.exception_handler(DriverRequestError)
    async def _driver_request_error(request: Request, exc: Exception):
        return _envelope(400, type(exc).__name__, str(exc), _clearance(request))

    @app.exception_handler(ReconciliationError)
    async def _reconciliation_error(request: Request, exc: Exception):
        # A data-integrity failure inside a governed engine, not a client
        # mistake -- 502, never 400/500-with-traceback.
        return _envelope(502, type(exc).__name__, str(exc), _clearance(request))

    @app.exception_handler(BudgetExceeded)
    async def _budget_exceeded(request: Request, exc: Exception):
        return _envelope(429, "BudgetExceeded", str(exc), _clearance(request))

    @app.exception_handler(InvalidTransitionError)
    @app.exception_handler(ReviewError)
    async def _conflict(request: Request, exc: Exception):
        return _envelope(409, type(exc).__name__, str(exc), _clearance(request))

    @app.exception_handler(FileNotFoundError)
    async def _not_found_data(request: Request, exc: Exception):
        return _envelope(503, "DataNotBuilt", str(exc), _clearance(request))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Never leak a raw traceback/exception message below INTERNAL
        # clearance -- redact_error_message strips id-shaped tokens.
        return _envelope(500, "InternalError", str(exc), _clearance(request))
