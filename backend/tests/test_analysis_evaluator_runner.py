"""The evaluator uses installed preservation code, never Python from an asset checkout."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def evaluator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "analysis_evaluator_test", ROOT / "scripts/evaluate-analysis.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assets = tmp_path / "assets"
    (assets / "scripts").mkdir(parents=True)
    (assets / "scripts/check-published-reads-runtime.py").write_text(
        "raise AssertionError('Asset-checkout code must never execute')", encoding="utf-8"
    )
    selected = object()
    load = Mock(return_value=selected)
    monkeypatch.setattr(module, "load_database_settings", load)
    for name in (
        "PublicationRepository",
        "ReadRepository",
        "EvidenceRepository",
        "EvidenceService",
        "SourceStorage",
        "native_ingestion_settings",
    ):
        monkeypatch.setattr(module, name, Mock())
    reads = Mock()
    reads.scope.return_value = SimpleNamespace(
        manifest=object(), info=object(), view=SimpleNamespace(observations=[])
    )
    reads.catalog.catalog.return_value = SimpleNamespace(entities=[], metrics=[])
    monkeypatch.setattr(module, "PublishedReadService", Mock(return_value=reads))
    monkeypatch.setattr(module, "ComparisonService", Mock())
    monkeypatch.setattr(module, "evaluate", Mock(return_value={"status": "BLOCKED"}))
    snapshots = Mock(return_value={"regintel.new_module_table": "a" * 64})
    monkeypatch.setattr(module, "snapshot_database", snapshots)
    return module, assets, selected, load, snapshots


def test_selected_assets_do_not_supply_executable_preservation_code(evaluator):
    module, assets, selected, load, snapshots = evaluator
    report = module.run(ROOT / "data/analysis-acceptance-plan.json", assets)
    load.assert_called_once_with(assets / ".env")
    assert snapshots.call_count == 2
    assert all(call.args == (selected,) for call in snapshots.call_args_list)
    assert report["state_tables_unchanged"] == 1
    assert report["state_snapshot_version"] == module.SNAPSHOT_VERSION
    assert report["provider_calls"] == 0


@pytest.mark.parametrize(
    "changed",
    [
        {},
        {"regintel.new_module_table": "b" * 64},
        {"regintel.new_module_table": "a" * 64, "regintel.added_table": "c" * 64},
    ],
)
def test_row_or_table_inventory_drift_fails_instead_of_returning_a_report(evaluator, changed):
    module, assets, _, _, snapshots = evaluator
    snapshots.side_effect = [{"regintel.new_module_table": "a" * 64}, changed]
    with pytest.raises(ValueError, match="Authoritative state changed"):
        module.run(ROOT / "data/analysis-acceptance-plan.json", assets)


def test_failed_service_assembly_still_checks_preservation(evaluator):
    module, assets, _, _, snapshots = evaluator
    module.PublishedReadService.side_effect = RuntimeError("authored assembly failure")
    with pytest.raises(RuntimeError, match="authored assembly failure"):
        module.run(ROOT / "data/analysis-acceptance-plan.json", assets)
    assert snapshots.call_count == 2
