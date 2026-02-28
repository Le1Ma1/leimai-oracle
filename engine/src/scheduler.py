from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import load_config
from .logging_setup import log_event
from .run_once import run_pipeline_once


def run_scheduled() -> None:
    cfg = load_config()
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        run_pipeline_once,
        trigger=IntervalTrigger(hours=cfg.schedule_tier1_hours),
        kwargs={"config": cfg, "timeframe_subset": ("1m", "5m"), "run_optimization": False},
        id="tier1",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        run_pipeline_once,
        trigger=IntervalTrigger(hours=cfg.schedule_tier2_hours),
        kwargs={"config": cfg, "timeframe_subset": ("15m", "1h"), "run_optimization": False},
        id="tier2",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        run_pipeline_once,
        trigger=IntervalTrigger(days=cfg.schedule_tier3_days),
        kwargs={"config": cfg, "timeframe_subset": ("4h", "1d", "1w"), "run_optimization": False},
        id="tier3",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        run_pipeline_once,
        trigger=IntervalTrigger(hours=cfg.optimization_schedule_hours),
        kwargs={"config": cfg, "timeframe_subset": cfg.aggregate_timeframes, "run_optimization": True},
        id="optimization",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    log_event(
        "SCHEDULER_START",
        tier1_hours=cfg.schedule_tier1_hours,
        tier2_hours=cfg.schedule_tier2_hours,
        tier3_days=cfg.schedule_tier3_days,
        optimization_hours=cfg.optimization_schedule_hours,
    )
    scheduler.start()


if __name__ == "__main__":
    run_scheduled()
