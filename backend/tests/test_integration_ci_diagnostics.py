"""CI diagnostics reveal bounded failing test identities without assertion payloads."""

import runpy
from pathlib import Path

import pytest


def test_ci_annotations_expose_identity_without_failure_or_captured_secrets(
    tmp_path, monkeypatch, capsys
):
    report = tmp_path / "result.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="tests.integration.test_authored" '
        'name="test_context[invalid]">'
        '<failure message="secret-assertion-value">raw secret traceback</failure>'
        "<system-out>captured credential value</system-out></testcase>"
        '<testcase classname="tests.passing" name="test_success" /></testsuite></testsuites>'
    )
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/check-migrations.py")
    )
    module["report_test_failures"](report)
    output = capsys.readouterr().out
    assert "tests.integration.test_authored::test_context" in output
    assert "[invalid]" not in output
    assert "::error title=Integration test failed::" in output
    assert "secret" not in output and "credential" not in output and "test_success" not in output


def test_bad_or_missing_reports_do_not_mask_original_exit_status(tmp_path, capsys):
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/check-migrations.py")
    )
    report = tmp_path / "result.xml"
    module["report_test_failures"](report)
    report.write_text("not XML")
    module["report_test_failures"](report)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["outside.xml", ".cache/wrong.txt"])
def test_report_target_is_rejected_before_database_access(name, monkeypatch, capsys):
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/check-migrations.py")
    )
    monkeypatch.setattr("sys.argv", ["check-migrations.py", "--junit-report", name])
    with pytest.raises(SystemExit) as error:
        module["main"]()
    assert error.value.code == 2
    assert "inside the project cache" in capsys.readouterr().err
