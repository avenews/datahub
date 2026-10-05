import pytest

from bot.crypto import DecryptionError, TokenCipher


def test_encrypt_then_decrypt_roundtrip():
    cipher = TokenCipher("a-very-secret-key")

    ciphertext = cipher.encrypt("datahub-pat-12345")

    assert ciphertext != b"datahub-pat-12345"
    assert cipher.decrypt(ciphertext) == "datahub-pat-12345"


def test_different_keys_cannot_decrypt_each_others_tokens():
    cipher_a = TokenCipher("key-a")
    cipher_b = TokenCipher("key-b")

    ciphertext = cipher_a.encrypt("secret-token")

    with pytest.raises(DecryptionError):
        cipher_b.decrypt(ciphertext)


def test_same_key_produces_working_cipher_across_instances():
    ciphertext = TokenCipher("shared-key").encrypt("token-value")

    assert TokenCipher("shared-key").decrypt(ciphertext) == "token-value"


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        TokenCipher("")
