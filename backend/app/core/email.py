"""Email address validation for identity provisioning.

Transactional email in Aetrix is sent by Supabase Auth, not by this engine: the
engine only verifies the JWTs Supabase issues.  Nothing in this module sends
mail.  Its purpose is narrower — to stop an address that can never receive mail
from being stored on a user record and then handed to the identity provider,
where every confirmation or recovery attempt counts as a bounce.

Validation is deliberately offline and dependency-free: syntax, plus the
reserved domains that RFC 2606 and RFC 6761 guarantee are undeliverable.
Reachability (a delegated domain with a working MX record) can only be confirmed
by DNS, so it remains an operator preflight documented in
``docs/engine/architecture/EMAIL_DELIVERABILITY.md`` rather than a rule that
would make this module network-dependent and non-deterministic in tests.
"""

from __future__ import annotations

import re

__all__ = [
    "RESERVED_DOMAINS",
    "RESERVED_SUFFIXES",
    "InvalidEmailAddress",
    "normalize_email",
    "validate_email",
]

#: Practical ceilings from RFC 5321 for the whole address and the local part.
MAX_ADDRESS_LENGTH = 320
MAX_LOCAL_LENGTH = 64
MAX_DOMAIN_LENGTH = 253
MAX_LABEL_LENGTH = 63

_LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_TOP_LEVEL_LABEL = re.compile(r"(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{1,59})")

#: Domains reserved for documentation (RFC 2606); they never accept mail.
RESERVED_DOMAINS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "example.edu",
        "localhost",
    }
)

#: Reserved or non-public suffixes that never accept mail (RFC 2606, RFC 6761,
#: and the private-use names commonly used in development).
RESERVED_SUFFIXES = (
    ".test",
    ".invalid",
    ".example",
    ".localhost",
    ".local",
    ".internal",
    ".home",
    ".corp",
    ".lan",
)


class InvalidEmailAddress(ValueError):
    """Raised when an address is malformed or permanently undeliverable."""


def normalize_email(value: str) -> str:
    """Return the address without surrounding whitespace and a lower-case domain.

    The local part keeps its case: only the domain is case-insensitive in
    address syntax, and silently rewriting the local part would change the
    mailbox.  This does not validate; call :func:`validate_email` for that.
    """
    if not isinstance(value, str):
        raise InvalidEmailAddress("An email address must be a string.")
    local, separator, domain = value.strip().rpartition("@")
    if not separator:
        raise InvalidEmailAddress("An email address must contain an '@'.")
    return f"{local}@{domain.lower()}"


def validate_email(value: str) -> str:
    """Validate and normalize an address, or raise :class:`InvalidEmailAddress`."""
    address = normalize_email(value)
    local, _, domain = address.partition("@")

    if not local or not domain:
        raise InvalidEmailAddress("An email address needs text before and after the '@'.")
    if len(address) > MAX_ADDRESS_LENGTH:
        raise InvalidEmailAddress(
            f"An email address cannot exceed {MAX_ADDRESS_LENGTH} characters."
        )
    if len(local) > MAX_LOCAL_LENGTH:
        raise InvalidEmailAddress(
            f"The part before '@' cannot exceed {MAX_LOCAL_LENGTH} characters."
        )
    if not _LOCAL_PART.fullmatch(local):
        raise InvalidEmailAddress(
            "The part before '@' contains characters or dot placement that address "
            "syntax does not allow."
        )

    if len(domain) > MAX_DOMAIN_LENGTH:
        raise InvalidEmailAddress(f"The domain cannot exceed {MAX_DOMAIN_LENGTH} characters.")
    labels = domain.split(".")
    if len(labels) < 2:
        raise InvalidEmailAddress("The domain needs a dot-separated top-level domain.")
    for label in labels:
        if not label:
            raise InvalidEmailAddress(
                "The domain contains an empty label (a doubled or trailing dot)."
            )
        if len(label) > MAX_LABEL_LENGTH or not _LABEL.fullmatch(label):
            raise InvalidEmailAddress(f"The domain label '{label}' is not valid.")
    if not _TOP_LEVEL_LABEL.fullmatch(labels[-1]):
        raise InvalidEmailAddress(f"'{labels[-1]}' is not a valid top-level domain.")

    _reject_undeliverable_domain(domain)
    return address


def _reject_undeliverable_domain(domain: str) -> None:
    """Refuse domains that are guaranteed never to accept mail.

    Rejecting these locally avoids a confirmation or recovery email that can
    only ever bounce, which is what inflates the provider's bounce rate.
    """
    if domain in RESERVED_DOMAINS:
        raise InvalidEmailAddress(
            f"The domain '{domain}' is reserved for documentation and cannot receive email."
        )
    for suffix in RESERVED_SUFFIXES:
        if domain.endswith(suffix):
            raise InvalidEmailAddress(
                f"The domain '{domain}' uses the reserved '{suffix}' suffix and "
                "cannot receive email."
            )
