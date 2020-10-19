class Conn:
    pass


class ConnException(Exception):
    pass


def listen(address: str) -> Conn:
    pass


def accept(conn) -> Conn:
    pass


def dial(address) -> Conn:
    pass


def send(conn: Conn, data: bytes) -> int:
    pass


def recv(conn: Conn, length: int) -> bytes:
    pass


def close(conn: Conn):
    pass
