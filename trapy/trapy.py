class Conn:
    """
    Base Conn class
    """
    pass


class ConnException(Exception):
    """
    Base Connection Exception
    """
    pass


def listen(address: str) -> Conn:
    """
    prepara una conexión que acepta los paquetes enviados a `address`.
    """
    pass


def accept(conn: Conn) -> Conn:
    """
    espera por alguna petición de conexión utilizando un `conn` creado previamente con `listen`.
    """
    pass


def dial(address) -> Conn:
    """
    establece conexión con el otro extremo indicado en `address` y devuelve la conexión.
    """
    pass


def send(conn: Conn, data: bytes) -> int:
    """
    envía los datos por la conexión y devuelve la cantidad de bytes enviados.
    """
    pass


def recv(conn: Conn, length: int) -> bytes:
    """
    bytes recibe a lo sumo length bytes almacenados en el buffer de la conexión.
    """
    pass


def close(conn: Conn):
    """
    termina la conexión.
    """
    pass
