"""Validate the pool's untested credentials with the real adapter.

Run from ``backend`` with the project venv.  It prints only the fingerprint, the
classification and the health transition — never the key, the ciphertext or the
Authorization header.  Each credential is validated individually, in order.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import ProviderCredential
from app.db.session import get_session_factory
from app.providers.factory import build_provider
from app.services import provider_fleet


def main() -> int:
    settings = get_settings()
    provider = build_provider(settings)
    print(f"provider={provider.name} live={settings.features.live_provider}")

    factory = get_session_factory(settings)
    with factory() as session:
        rows = list(
            session.scalars(
                select(ProviderCredential)
                .where(
                    ProviderCredential.project_id == "user-downloads-pool",
                    ProviderCredential.health.in_(["UNKNOWN", "UNREACHABLE"]),
                )
                .order_by(ProviderCredential.created_at)
            )
        )
        print(f"candidates={len(rows)}")
        for row in rows:
            print(f"- id={row.id} project={row.project_id} fp={row.key_fingerprint}")
            result = provider_fleet.validate_credential(
                session, settings, provider, row
            )
            print(
                "  valid={valid} health={health} category={category} "
                "http={http_status} model={model} latency={latency_ms} "
                "checked_at={checked_at}".format(**result)
            )
            print(f"  detail={result['detail']}")
            print(f"  provider_message={result['provider_message']}")
            print(f"  recommendation={result['recommendation']}")

        print("--- stored state ---")
        for row in session.scalars(
            select(ProviderCredential)
            .where(ProviderCredential.project_id == "user-downloads-pool")
            .order_by(ProviderCredential.created_at)
        ):
            print(
                f"- fp={row.key_fingerprint} health={row.health} "
                f"last_failure_status={row.last_failure_status} "
                f"last_validated_at={row.last_validated_at} "
                f"last_error={row.last_error}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
