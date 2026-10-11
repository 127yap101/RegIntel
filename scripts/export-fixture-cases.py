"""Generate ignored frontend case data; --check detects drift without writing."""

import argparse
from pathlib import Path

from regintel.fixtures.adversarial import fixture_cases, verify_case_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    suite = fixture_cases()
    verify_case_suite(suite)
    expected = (suite.model_dump_json(indent=2) + "\n").encode("utf-8")
    root = Path(__file__).resolve().parents[1]
    path = root / "frontend/src/contracts/fixtures.generated.json"
    if options.check:
        if not path.is_file() or path.read_bytes() != expected:
            print("Fixture cases differ; run scripts/export-fixture-cases.py.")
            return 1
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(expected)
    print("Fixture case data matches." if options.check else "Fixture case data generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
