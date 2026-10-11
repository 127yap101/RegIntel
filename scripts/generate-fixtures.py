"""Generate synthetic M0.6 PDFs/manifest, or verify them without rewriting artifacts."""

import argparse
from pathlib import Path

from regintel.fixtures.pdf import FixtureGenerationError, generate_fixture_family


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify existing artifacts without writing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Must be this workspace's artifacts/fixtures directory.",
    )
    options = parser.parse_args()
    try:
        paths = generate_fixture_family(options.output, check=options.check)
    except FixtureGenerationError as error:
        print(f"Fixture verification failed: {error}")
        return 1
    print(
        f"Synthetic fixture {'verification' if options.check else 'generation'} passed: "
        f"{len(paths) - 1} PDFs and one manifest."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
