from mailcpu.model import Message
from mailcpu.transport import InMemoryTransport


def test_fifo_poll_and_non_consuming_list() -> None:
    """Mathematics: verify `list(Q)` is observational and `poll(Q)` removes exactly its FIFO head."""

    transport = InMemoryTransport()
    first = transport.send("mailbox", Message(value=1))
    second = transport.send("mailbox", Message(value=2))
    assert [message.value for message in transport.list("mailbox")] == [1, 2]
    assert transport.poll("mailbox") == first
    assert transport.list("mailbox") == (second,)


def test_consume_removes_by_message_identity() -> None:
    """Mathematics: verify consuming identity `m` changes `Q` only when `m ∈ Q`."""

    transport = InMemoryTransport()
    first = transport.send("mailbox", Message(value=1))
    second = transport.send("mailbox", Message(value=2))
    assert transport.consume(first) is True
    assert transport.consume(first) is False
    assert transport.list("mailbox") == (second,)
