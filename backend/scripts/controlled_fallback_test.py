"""Prove model fallback through the production provider service.

The *primary* failure is simulated at the HTTP transport boundary: the first
model in the marking chain is answered with a 503 that never leaves this
process.  Everything after that is real — the same ``ProviderCallService.call``
the marking pipeline uses, the same credential pool, the same usage ledger, and
a real Gemini request to the next model in the configured chain.

This is not a provider outage and it is not a benchmark.  It answers one
question: when the primary model fails under the routing policy, does the
production call path really move to the next model and record that it did?

Usage::

    python scripts/controlled_fallback_test.py --block gemini-3.1-flash-lite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from app.core.config import get_settings
from app.core.ids import utcnow
from app.core.security import fingerprint
from app.db.models import ProviderUsage
from app.db.repositories import CredentialRepository
from app.db.session import session_scope
from app.prompts.registry import PromptRegistry
from app.providers.gemini import GeminiProvider
from app.services.provider_calls import ProviderCallService
from app.services.provider_fleet import add_credential
from pydantic import SecretStr
from sqlalchemy import select

KEY_FILE = Path(__file__).resolve().parents[2] / ".tmp" / "secure" / "gemini-test-key.txt"
PROJECT = "user-downloads-pool"
PURPOSE = "CONTROLLED_FALLBACK_TEST"


class InterceptTransport(httpx.BaseTransport):
    """Answer one model with a synthetic 503; pass everything else through."""

    def __init__(self, blocked_model: str, status: int = 503) -> None:
        self.blocked_model = blocked_model
        self.status = status
        self._real = httpx.HTTPTransport()
        self.intercepted = 0
        self.passed_through: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if f"/models/{self.blocked_model}:" in url:
            self.intercepted += 1
            return httpx.Response(
                self.status,
                json={
                    "error": {
                        "code": self.status,
                        "status": "UNAVAILABLE",
                        "message": "Simulated provider outage injected by the "
                        "controlled fallback test.",
                    }
                },
                request=request,
            )
        self.passed_through.append(url.split("/models/")[-1].split(":")[0])
        return self._real.handle_request(request)


def _key() -> SecretStr:
    return SecretStr(KEY_FILE.read_text(encoding="utf-8").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", default="", help="model to answer with a 503")
    parser.add_argument("--attempts", type=int, default=2, help="attempts per model")
    arguments = parser.parse_args()

    settings = get_settings()
    blocked = arguments.block or settings.provider.model_chains["primary"][0].model
    provider_settings = settings.provider.model_copy(
        update={"max_attempts": arguments.attempts, "retry_backoff_seconds": 0.0}
    )
    settings = settings.model_copy(update={"provider": provider_settings})

    transport = InterceptTransport(blocked)
    provider = GeminiProvider(
        base_url=settings.provider.gemini_base_url,
        timeout_seconds=120,
        transport=transport,
        thinking_budget=settings.provider.thinking_budget,
    )

    started = utcnow()
    with session_scope() as session:
        api_key = _key()
        credentials = CredentialRepository(session)
        existing = credentials.get_by_fingerprint(fingerprint(api_key.get_secret_value()))
        if existing is None:
            credential = add_credential(
                session,
                settings,
                project_id=PROJECT,
                api_key=api_key,
                label="controlled fallback test key",
            )
            print(f"registered credential {credential.id} under project {PROJECT}")
        else:
            credential = existing
            print(f"using existing credential {credential.id} under project {PROJECT}")
        credential_id = credential.id

        service = ProviderCallService(
            session,
            settings,
            provider,
            PromptRegistry(settings.provider.prompt_root),
        )
        print("chain:", [entry.model for entry in service.model_chain("primary")])

        result = service.call(
            tenant_id=_tenant_id(session),
            purpose=PURPOSE,
            prompt_id="blueprint_extraction",
            inputs=(),
            response_schema=None,
            max_output_tokens=1024,
        )

        print("\nRESULT")
        print("  simulated 503s at transport:", transport.intercepted)
        print("  real model calls passed through:", transport.passed_through)
        print("  answering model:", result.response.model)
        print("  chain position:", result.model_chain_position)
        print("  models attempted:", list(result.models_attempted))
        print("  provider request id:", result.response.provider_request_id)
        print("  usage id:", result.usage_id)
        print("  response chars:", len(result.response.text))
        print("  usage:", result.response.usage)

        print("\nLEDGER ROWS FOR THIS CREDENTIAL AND PURPOSE")
        rows = session.scalars(
            select(ProviderUsage)
            .where(
                ProviderUsage.purpose == PURPOSE,
                ProviderUsage.created_at >= started,
            )
            .order_by(ProviderUsage.created_at)
        ).all()
        for row in rows:
            print(
                f"  {row.model:26s} pos={row.model_chain_position} "
                f"attempt={row.attempt_index} http={row.http_status} "
                f"decision={row.routing_decision} category={row.error_category} "
                f"in={row.input_tokens} out={row.output_tokens} "
                f"cost={row.cost_usd} cost_status={row.cost_status} "
                f"latency={row.latency_ms}ms success={row.success}"
            )
        print(f"\ncredential used: {credential_id}")
    return 0


def _tenant_id(session) -> object:
    """The pilot workspace, which owns this deployment's credentials."""

    from app.db.models import Tenant

    tenant = session.scalar(select(Tenant).limit(1))
    if tenant is None:
        raise SystemExit("no tenant exists in this database")
    return tenant.id


if __name__ == "__main__":
    sys.exit(main())
