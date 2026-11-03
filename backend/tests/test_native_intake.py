"""Preparation integrity and command boundaries over explicitly authored captures."""

import json
import warnings
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.tests.native_intake_fixtures import intake_case, reference
from regintel.parsing.intake import load_intake_plan, prepare_intake
from regintel.parsing.intake_cli import main
from regintel.parsing.intake_models import NativeIntakePlan


@pytest.fixture
def declared(tmp_path):
    return intake_case(tmp_path)


def test_complete_preparation_replays_without_database_or_parser_sdk(declared, tmp_path):
    case, plan = declared
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = prepare_intake(plan)
    assert result.check.source_sha256 == plan.source.sha256
    assert result.check.source_pages == 2 and result.check.evidence_pdf_pages == (2,)
    assert result.check.processing_configuration_sha256 == (
        case.result.configuration.processing_configuration_sha256
    )
    assert result.check.prepared_sha256 == (case.result.captures[0].stored.prepared_sha256,)
    assert not result.check.acceptance_eligible
    assert before == sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert result.check == prepare_intake(plan).check


@pytest.mark.parametrize("field", ["source", "parser_configuration", "native_manifest"])
def test_changed_explicit_input_is_rejected_before_success(declared, field):
    _, plan = declared
    selected = getattr(plan, field)
    Path(selected.path).write_bytes(Path(selected.path).read_bytes() + b"\n")
    with pytest.raises(ValueError):
        prepare_intake(plan)


@pytest.mark.parametrize("change", ["raw_hash", "wrong_page", "foreign_source", "duplicate_key"])
def test_context_membership_and_ambiguous_json_fail_closed(declared, change):
    _, plan = declared
    selected = plan.context_pages[0]
    path = Path(selected.raw_capture.path)
    raw = json.loads(path.read_bytes())
    if change == "raw_hash":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "wrong_page":
        selected = selected.model_copy(update={"pdf_page": 1})
    else:
        if change == "foreign_source":
            raw["original_source_sha256"] = "0" * 64
            body = json.dumps(raw).encode()
        else:
            body = path.read_bytes().replace(b"{", b'{"status":"SUCCESS",', 1)
        path.write_bytes(body)
        selected = selected.model_copy(update={"raw_capture": reference(path)})
    with pytest.raises(ValueError):
        prepare_intake(plan.model_copy(update={"context_pages": (selected,)}))


def test_native_page_tampering_is_not_hidden_by_a_valid_manifest(declared):
    case, plan = declared
    path = case.result.bank.directory / "page-0000.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        prepare_intake(plan)


@pytest.mark.parametrize("pages", [[], [2, 2], [2, 1], [True], [0], [2001], list(range(1, 34))])
def test_explicit_page_selection_is_bounded_unique_and_ordered(declared, pages):
    _, plan = declared
    value = plan.model_dump(mode="json")
    page = value["context_pages"][0]
    value["context_pages"] = [dict(page, pdf_page=index) for index in pages]
    with pytest.raises(ValidationError):
        NativeIntakePlan.model_validate(value)


def test_plan_rejects_duplicate_keys_and_unknown_authority_fields(declared, tmp_path):
    _, plan = declared
    path = tmp_path / "plan.json"
    path.write_text('{"source":null,' + plan.model_dump_json()[1:], encoding="utf-8")
    with pytest.raises(ValueError):
        load_intake_plan(path)
    value = plan.model_dump(mode="json") | {"acceptance_eligible": True}
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        load_intake_plan(path)


@pytest.mark.parametrize("change", ["relative", "directory", "oversize"])
def test_nonregular_or_unbounded_explicit_files_are_rejected(declared, tmp_path, change):
    _, plan = declared
    ref = plan.source
    if change == "relative":
        ref = ref.model_copy(update={"path": "relative.pdf"})
    elif change == "directory":
        ref = ref.model_copy(update={"path": str(tmp_path)})
    else:
        path = tmp_path / "large.json"
        path.write_bytes(b" " * (256 * 1024 + 1))
        with pytest.raises(ValueError):
            load_intake_plan(path)
        return
    with pytest.raises(ValueError):
        prepare_intake(plan.model_copy(update={"source": ref}))


def test_aggregate_context_limit_is_enforced_before_the_next_allocation(declared, monkeypatch):
    _, plan = declared
    import regintel.parsing.intake as module

    monkeypatch.setattr(module, "MAX_CONTEXT_BYTES", 10)
    with pytest.raises(ValueError):
        prepare_intake(plan)


@pytest.mark.parametrize("change", ["code", "bytes", "pages"])
def test_selected_runtime_limits_and_installed_identity_remain_mandatory(declared, change):
    _, plan = declared
    path = Path(plan.parser_configuration.path)
    runtime = json.loads(path.read_bytes())
    if change == "code":
        runtime["adapter_code_sha256"] = "0" * 64
    else:
        key = "max_file_bytes" if change == "bytes" else "max_pages"
        runtime["source_limits"][key] = 1
    path.write_text(json.dumps(runtime), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_intake(plan.model_copy(update={"parser_configuration": reference(path)}))


def test_command_check_needs_no_auth_and_reports_no_temporary_ids(
    declared, tmp_path, monkeypatch, capsys
):
    _, plan = declared
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["intake", "check", "--plan", str(path)])
    assert main() == 0
    printed = capsys.readouterr()
    receipt = json.loads(printed.out)
    assert receipt["status"] == "PREPARATION_ONLY" and not receipt["acceptance_eligible"]
    assert "id" not in receipt and "path" not in printed.out and printed.err == ""


def test_command_failure_omits_raw_source_paths_and_diagnostics(tmp_path, monkeypatch, capsys):
    path = tmp_path / "private-source-and-secrets.json"
    path.write_text("PRIVATE MALFORMED SOURCE", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["intake", "check", "--plan", str(path)])
    assert main() == 1
    printed = capsys.readouterr()
    assert printed.out == ""
    assert json.loads(printed.err) == {"status": "INTAKE_FAILED", "acceptance_eligible": False}


def test_import_requires_explicit_installation_and_existing_account(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["intake", "import", "--plan", "plan.json"])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "Import requires" in capsys.readouterr().err


def test_import_without_a_private_password_prompt_fails_before_storage(
    declared, tmp_path, monkeypatch, capsys
):
    import getpass

    import regintel.parsing.intake_cli as cli

    _, plan = declared
    path = tmp_path / "plan.json"
    path.write_text(plan.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(cli, "load_database_settings", lambda _: None)
    monkeypatch.setattr(cli, "load_auth_settings", lambda _: None)
    monkeypatch.setattr(cli, "PostgreSQLAuthRepository", lambda _: None)
    monkeypatch.setattr(cli, "AuthService", lambda *_: None)

    def no_private_terminal(_):
        warnings.warn("No private terminal", getpass.GetPassWarning, stacklevel=2)
        pytest.fail("Password fallback must never run")

    monkeypatch.setattr(getpass, "getpass", no_private_terminal)
    monkeypatch.setattr(
        "sys.argv",
        [
            "intake",
            "import",
            "--plan",
            str(path),
            "--project-root",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
            "--auth-env-file",
            str(tmp_path / ".env.auth"),
            "--username",
            "admin",
        ],
    )
    assert main() == 1
    printed = capsys.readouterr()
    assert printed.out == "" and "INTAKE_FAILED" in printed.err
    assert not (tmp_path / "data").exists()
