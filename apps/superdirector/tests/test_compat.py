from __future__ import annotations

from datetime import timezone
import importlib

from compat import UTC

MODULES = (
    "api.routes",
    "core.scheduler",
    "db.crud",
    "db.models",
    "integrations.bitable_writer",
    "pipeline.backtest",
    "pipeline.collector",
    "pipeline.feedback_collector",
    "pipeline.feedback_review",
    "pipeline.scoring_config",
)


def test_utc_alias_is_timezone_utc():
    assert UTC is timezone.utc


def test_modules_import_with_compat_utc():
    for module_name in MODULES:
        importlib.import_module(module_name)
