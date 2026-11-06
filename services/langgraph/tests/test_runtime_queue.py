from services.langgraph.app.in_memory_queue import BoundedInMemoryQueue, DuplicateOperationError, QueueFullError


def test_bounded_queue_rejects_duplicate_operation_id():
    queue = BoundedInMemoryQueue(maxsize=2)
    queue.put_nowait(operation_id="op-1", payload={"x": 1})
    try:
        queue.put_nowait(operation_id="op-1", payload={"x": 2})
        assert False, "expected DuplicateOperationError"
    except DuplicateOperationError:
        pass


def test_bounded_queue_rejects_when_full():
    queue = BoundedInMemoryQueue(maxsize=1)
    queue.put_nowait(operation_id="op-1", payload={"x": 1})
    try:
        queue.put_nowait(operation_id="op-2", payload={"x": 2})
        assert False, "expected QueueFullError"
    except QueueFullError:
        pass

