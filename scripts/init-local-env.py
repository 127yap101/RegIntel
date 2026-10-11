"""Create new project-local development credentials without reading/overwriting any."""

import os
import secrets
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / ".env"
    postgres_password = secrets.token_hex(32)
    content = "\n".join(
        [
            "# Generated local development credentials. Never commit this file.",
            "POSTGRES_USER=regintel",
            "POSTGRES_DB=regintel",
            f"POSTGRES_PASSWORD={postgres_password}",
            f"NEO4J_AUTH=neo4j/{secrets.token_hex(32)}",
            f"REDIS_PASSWORD={secrets.token_hex(32)}",
            "REGINTEL_DATABASE_URL=postgresql://regintel:"
            f"{postgres_password}@127.0.0.1:5432/regintel",
            "",
        ]
    )
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(
            ".env already exists; left it untouched. No credentials printed."
        ) from None
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    print("Created ignored project .env. No credentials printed.")


if __name__ == "__main__":
    main()
