"""QA regression: incomplete standards fields are not systemic collector faults."""
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "backfill_controller.py"
spec = importlib.util.spec_from_file_location("sl_backfill", SRC)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_incomplete_standards_fields_stay_flagged_but_do_not_stop_bulk_collection():
    row = {
        "qa_flags": (
            "missing_surface|missing_going|missing_running_comments|"
            "unconverted_symbolic_margins|course_configuration_unverified"
        )
    }
    all_flags, critical = module.severity_flags(row)
    assert "missing_surface" in all_flags
    assert "missing_running_comments" in all_flags
    assert critical == []


def test_structural_broken_rows_still_stop_collection():
    row = {
        "qa_flags": (
            "runner_count_mismatch|finish_order_gap_or_duplicate|"
            "no_finishers_parsed|unmatched_horse_12"
        )
    }
    _, critical = module.severity_flags(row)
    assert len(critical) == 4, critical


def test_no_standards_auto_approval():
    assert "standards_input_allowed INTEGER NOT NULL DEFAULT 0" in SRC.read_text()
