"""Exclusively generate new ignored M0.4 local credentials without reading old secrets."""

import os
import secrets
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parents[1] / ".env.auth"
    content = "\n".join(
        [
            "# Local development authentication. Never commit or print this file.",
            f"REGINTEL_JWT_SECRET={secrets.token_hex(32)}",
            "REGINTEL_AUTH_ISSUER=regintel-finance",
            "REGINTEL_AUTH_AUDIENCE=regintel-api",
            "REGINTEL_AUTH_TOKEN_TTL_SECONDS=1800",
            "REGINTEL_SEED_ADMIN_USERNAME=admin",
            f"REGINTEL_SEED_ADMIN_PASSWORD={secrets.token_urlsafe(32)}",
            "REGINTEL_SEED_LEARNER_USERNAME=learner",
            f"REGINTEL_SEED_LEARNER_PASSWORD={secrets.token_urlsafe(32)}",
            "",
        ]
    )
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env.auth already exists; unchanged. No secrets printed.") from None
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    print("Created ignored .env.auth with new local credentials; no secrets printed.")


if __name__ == "__main__":
    main()
