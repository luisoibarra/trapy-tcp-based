from trapy.tcp.trapy import Conn, ConnException
from trapy.tcp.trapy import listen as tcp_listen
from trapy.tcp.trapy import accept as tcp_accept
from trapy.tcp.trapy import dial   as tcp_dial
from trapy.tcp.trapy import send   as tcp_send
from trapy.tcp.trapy import recv   as tcp_recv
from trapy.tcp.trapy import close  as tcp_close
from trapy.tcp.tcp import TCP

def listen(address: str) -> Conn:
    """
    prepara una conexión que acepta los paquetes enviados a `address`.
    """
    return tcp_listen(address)


def accept(conn: Conn) -> Conn:
    """
    espera por alguna petición de conexión utilizando un `conn` creado previamente con `listen`.
    """
    return tcp_accept(conn)


def dial(address) -> Conn:
    """
    establece conexión con el otro extremo indicado en `address` y devuelve la conexión.
    """
    return tcp_dial(address)


def send(conn: Conn, data: bytes) -> int:
    """
    envía los datos por la conexión y devuelve la cantidad de bytes enviados.
    """
    return tcp_send(conn, data)


def recv(conn: Conn, length: int) -> bytes:
    """
    bytes recibe a lo sumo length bytes almacenados en el buffer de la conexión.
    """
    return tcp_recv(conn, length)


def close(conn: Conn):
    """
    termina la conexión.
    """
    return tcp_close(conn)
