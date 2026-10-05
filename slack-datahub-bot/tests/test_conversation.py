from bot.conversation import ThreadContextStore


def test_new_thread_has_empty_history():
    store = ThreadContextStore()
    assert store.get_history("thread-1") == []


def test_append_turn_then_get_history_returns_both_messages():
    store = ThreadContextStore()

    store.append_turn("thread-1", "what is dataset x?", "It's a table.")

    history = store.get_history("thread-1")
    assert history == [
        {"role": "user", "content": "what is dataset x?"},
        {"role": "assistant", "content": "It's a table."},
    ]


def test_threads_are_isolated():
    store = ThreadContextStore()
    store.append_turn("thread-1", "q1", "a1")

    assert store.get_history("thread-2") == []


def test_history_is_capped_to_max_turns():
    store = ThreadContextStore(max_turns_per_thread=2)
    for i in range(5):
        store.append_turn("thread-1", f"q{i}", f"a{i}")

    history = store.get_history("thread-1")
    assert len(history) == 4  # 2 turns * 2 messages
    assert history[0]["content"] == "q3"
    assert history[-1]["content"] == "a4"


def test_expired_thread_is_treated_as_new(monkeypatch):
    store = ThreadContextStore(ttl_seconds=10)
    store.append_turn("thread-1", "q", "a")

    fake_time = [0.0]
    monkeypatch.setattr(store, "_now", lambda: fake_time[0])
    store.append_turn("thread-1", "q2", "a2")
    fake_time[0] = 1000.0

    assert store.get_history("thread-1") == []


def test_clear_removes_thread():
    store = ThreadContextStore()
    store.append_turn("thread-1", "q", "a")

    store.clear("thread-1")

    assert store.get_history("thread-1") == []
