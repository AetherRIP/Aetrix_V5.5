"""One bounded live Gemini smoke test.

Reads the authorized V5 key file read-only, tries at most three keys, and prints
only non-secret metadata.  It never writes, copies, echoes or logs a key.  This
is an acceptance probe, not a test-suite mock: a failure is reported as a
failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.providers.base import LLMRequest
from app.providers.errors import ProviderError
from app.providers.gemini import GeminiProvider
from pydantic import SecretStr


def _read_keys(path: Path) -> list[str]:
    keys: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "=" in value and not value.startswith("AIza"):
            value = value.split("=", 1)[1].strip()
        if value:
            keys.append(value)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--key-file",
        default=r"C:\Projects\MATH_CHECKER_V5\API_KEYS.txt",
        type=Path,
    )
    parser.add_argument("--model", default="gemini-3.6-flash")
    parser.add_argument("--attempts", default=3, type=int)
    args = parser.parse_args()

    if not args.key_file.is_file():
        print(json.dumps({"status": "UNVERIFIED", "failure": "key file not found"}))
        return 2
    keys = _read_keys(args.key_file)
    if not keys:
        print(json.dumps({"status": "UNVERIFIED", "failure": "key file contains no keys"}))
        return 2

    provider = GeminiProvider(base_url="https://generativelanguage.googleapis.com/v1beta")
    request = LLMRequest(
        model=args.model,
        prompt='Return exactly one JSON object: {"ok": true}. Do not add prose.',
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
        max_output_tokens=256,
    )
    failures: list[str] = []
    for index, key in enumerate(keys[: max(1, min(args.attempts, 6))]):
        try:
            response = provider.generate(request, SecretStr(key))
        except ProviderError as error:
            failures.append(
                f"key#{index + 1}:{type(error).__name__}:{error.status_code or 'no-status'}"
            )
            continue
        print(
            json.dumps(
                {
                    "status": "VERIFIED",
                    "keys_probed": index + 1,
                    "model": response.model,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cached_tokens": response.usage.cached_tokens,
                    "latency_ms": response.latency_ms,
                    "answer": response.text[:200],
                    "failures_before_success": failures,
                }
            )
        )
        return 0
    print(
        json.dumps(
            {
                "status": "UNVERIFIED",
                "keys_probed": min(len(keys), max(1, min(args.attempts, 6))),
                "failures": failures,
            }
        )
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
