"""APScheduler setup (Level 11).

Jobs open their own DB session, run inside ``transaction()`` (commit or roll
back) and never raise into the scheduler. A module-level singleton plus
``max_instances=1`` / ``coalesce=True`` prevents duplicate scheduler instances
and overlapping runs.
"""
import logging
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal
from app.services import assignment_service, coupon_service, delivery_service, order_service
from app.utils.constants import PARTNER_OFFLINE_AFTER_MINUTES

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _run(name: str, func: Callable, *args):
    """Run a service function with a fresh session; log and swallow errors."""
    db = SessionLocal()
    try:
        result = func(db, *args)
        if result:
            logger.info("job %s -> %s", name, result)
        return result
    except Exception:
        logger.exception("scheduled job %s failed", name)
        return None
    finally:
        db.close()


def job_auto_reject_orders():
    """Reject orders left in 'Placed' for > 5 minutes (reason: Restaurant did not respond)."""
    return _run("auto_reject_orders", order_service.auto_reject_stale_orders)


def job_expire_offers():
    """Expire offers older than 30 s and offer to the next nearest partner."""
    return _run("expire_offers", assignment_service.expire_offers)


def job_retry_unassigned():
    """Retry unassigned deliveries; alert admin after 15 minutes."""
    return _run("retry_unassigned", assignment_service.retry_unassigned)


def job_partners_offline():
    """Set partners offline after 10 minutes without a location update."""
    return _run("partners_offline", delivery_service.set_offline_if_stale, PARTNER_OFFLINE_AFTER_MINUTES)


def job_deactivate_coupons():
    """Deactivate expired coupons."""
    return _run("deactivate_coupons", coupon_service.deactivate_expired)


def build_scheduler() -> BackgroundScheduler:
    """Create a scheduler with all jobs registered (not started)."""
    scheduler = BackgroundScheduler(timezone="UTC")
    common = dict(max_instances=1, coalesce=True, misfire_grace_time=30, replace_existing=True)
    scheduler.add_job(job_auto_reject_orders, "interval", seconds=30, id="auto_reject_orders", **common)
    scheduler.add_job(job_expire_offers, "interval", seconds=5, id="expire_offers", **common)
    scheduler.add_job(job_retry_unassigned, "interval", minutes=1, id="retry_unassigned", **common)
    scheduler.add_job(job_partners_offline, "interval", minutes=5, id="partners_offline", **common)
    scheduler.add_job(job_deactivate_coupons, "cron", hour=0, minute=5, id="deactivate_coupons", **common)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Start the singleton scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    logger.info("scheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    """Shut the scheduler down cleanly (waits for running jobs)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("scheduler stopped")
    _scheduler = None


def get_scheduler() -> Optional[BackgroundScheduler]:
    return _scheduler
