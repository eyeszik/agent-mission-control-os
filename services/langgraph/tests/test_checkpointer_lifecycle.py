from services.langgraph.persistence.checkpoints import close_checkpointer, get_checkpointer


def test_checkpointer_is_process_owned_and_reused():
    first = get_checkpointer()
    second = get_checkpointer()
    assert first is second
    close_checkpointer()


def test_checkpointer_can_be_recreated_after_explicit_close():
    first = get_checkpointer()
    close_checkpointer()
    second = get_checkpointer()
    assert first is not second
    close_checkpointer()
