"""Routes for runtime settings and for manually triggering a scan."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db import get_db, session_scope
from backend.schemas import ScanResult, SettingsOut, SettingsUpdate
from backend.services.scanner import run_scan
from backend.services.settings_store import get_effective_settings, update_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
scan_router = APIRouter(prefix="/api", tags=["scan"])


def _to_out(eff) -> SettingsOut:
    return SettingsOut(**eff.as_public_dict())


@router.get("", response_model=SettingsOut)
def read_settings(db: Session = Depends(get_db)) -> SettingsOut:
    """Return the currently effective (overridable) settings."""
    return _to_out(get_effective_settings(db))


@router.patch("", response_model=SettingsOut)
def patch_settings(
    payload: SettingsUpdate, db: Session = Depends(get_db)
) -> SettingsOut:
    """Update a subset of settings; unspecified fields are left unchanged."""
    eff = update_settings(db, payload.model_dump(exclude_none=True))
    db.commit()
    return _to_out(eff)


@scan_router.post("/scan", response_model=ScanResult)
def trigger_scan() -> ScanResult:
    """Run one scan cycle now (synchronous) and return its summary."""
    with session_scope() as session:
        return run_scan(session)
