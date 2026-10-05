from bot.storage import UserStore


def test_save_and_get_roundtrip(tmp_path):
    store = UserStore(str(tmp_path / "bot.db"))

    store.save("U123", b"encrypted-bytes", "jane.doe", "urn:li:corpuser:jane.doe")

    user = store.get("U123")
    assert user is not None
    assert user.slack_user_id == "U123"
    assert user.encrypted_token == b"encrypted-bytes"
    assert user.datahub_username == "jane.doe"
    assert user.datahub_urn == "urn:li:corpuser:jane.doe"
    assert user.connected_at


def test_get_missing_user_returns_none(tmp_path):
    store = UserStore(str(tmp_path / "bot.db"))

    assert store.get("does-not-exist") is None


def test_save_overwrites_existing_token(tmp_path):
    store = UserStore(str(tmp_path / "bot.db"))
    store.save("U123", b"old-token", "jane.doe", "urn:li:corpuser:jane.doe")

    store.save("U123", b"new-token", "jane.doe", "urn:li:corpuser:jane.doe")

    user = store.get("U123")
    assert user.encrypted_token == b"new-token"


def test_delete_removes_user_and_reports_result(tmp_path):
    store = UserStore(str(tmp_path / "bot.db"))
    store.save("U123", b"token", "jane.doe", "urn:li:corpuser:jane.doe")

    deleted = store.delete("U123")

    assert deleted is True
    assert store.get("U123") is None


def test_delete_missing_user_returns_false(tmp_path):
    store = UserStore(str(tmp_path / "bot.db"))

    assert store.delete("does-not-exist") is False


def test_store_persists_across_instances(tmp_path):
    db_path = str(tmp_path / "bot.db")
    UserStore(db_path).save("U123", b"token", "jane.doe", "urn:li:corpuser:jane.doe")

    reopened = UserStore(db_path)

    assert reopened.get("U123") is not None
