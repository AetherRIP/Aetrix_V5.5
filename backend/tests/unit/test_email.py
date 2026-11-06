from __future__ import annotations

import pytest
from app.core.email import InvalidEmailAddress, normalize_email, validate_email


def test_accepts_a_deliverable_address() -> None:
    assert validate_email("teacher@school.edu") == "teacher@school.edu"


def test_normalizes_whitespace_and_domain_case_only() -> None:
    assert validate_email("  Teacher.Name@School.EDU  ") == "Teacher.Name@school.edu"
    assert normalize_email("MixedCase@Example.ORG").endswith("@example.org")


@pytest.mark.parametrize(
    "address",
    [
        "demo@aetrix.test",
        "owner@example.com",
        "user@example.net",
        "user@example.org",
        "root@localhost",
        "user@host.invalid",
        "user@printer.local",
        "user@service.internal",
        "user@box.lan",
    ],
)
def test_rejects_reserved_and_permanently_undeliverable_domains(address: str) -> None:
    with pytest.raises(InvalidEmailAddress):
        validate_email(address)


@pytest.mark.parametrize(
    "address",
    [
        "",
        "   ",
        "no-at-sign",
        "two@@school.edu",
        "a@@school.edu",
        "trailing@",
        "@school.edu",
        "spaces in@school.edu",
        "user@school",
        "user@-school.edu",
        "user@school..edu",
        "user@school.edu.",
        "user@school.e",
        "user@school.123",
        "user@school.edu-",
        ".leading@school.edu",
        "trailing.@school.edu",
        "double..dot@school.edu",
    ],
)
def test_rejects_malformed_addresses(address: str) -> None:
    with pytest.raises(InvalidEmailAddress):
        validate_email(address)


def test_rejects_over_length_parts() -> None:
    with pytest.raises(InvalidEmailAddress):
        validate_email(f"{'a' * 65}@school.edu")
    with pytest.raises(InvalidEmailAddress):
        validate_email(f"user@{'a' * 64}.edu")


def test_rejects_a_non_string_value() -> None:
    with pytest.raises(InvalidEmailAddress):
        validate_email(None)  # type: ignore[arg-type]
