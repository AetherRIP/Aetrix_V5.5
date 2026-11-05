from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.core.security import SecretBox, fingerprint
from cryptography.fernet import Fernet


def test_secret_box_round_trip() -> None:
    key = Fernet.generate_key().decode()
    box = SecretBox(key)
    token = box.encrypt("provider-key-value")
    assert "provider-key-value" not in token
    assert box.decrypt(token) == "provider-key-value"


def test_secret_box_rejects_a_different_key() -> None:
    first = SecretBox(Fernet.generate_key().decode())
    second = SecretBox(Fernet.generate_key().decode())
    token = first.encrypt("provider-key-value")
    with pytest.raises(AppError):
        second.decrypt(token)


def test_fingerprint_is_stable_and_not_the_secret() -> None:
    value = "AIza-not-a-real-key"
    assert fingerprint(value) == fingerprint(value)
    assert fingerprint(value) != value
    assert len(fingerprint(value)) == 16
