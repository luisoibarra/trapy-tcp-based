from trapy.tcp.tcp import *


def listen(address: str) -> TCPConnServer:
    """
    prepara una conexión que acepta los paquetes enviados a `address`.
    """
    return TCP.start_server(address)


def accept(conn: TCPConnServer) -> TCPConn:
    """
    espera por alguna petición de conexión utilizando un `conn` creado previamente con `listen`.
    """
    return TCP.accept(conn)


def dial(address:str) -> TCPConn:
    """
    establece conexión con el otro extremo indicado en `address` y devuelve la conexión.
    """
    return TCP.start_connection(address)


def send(conn: TCPConn, data: bytes) -> int:
    """
    envía los datos por la conexión y devuelve la cantidad de bytes enviados.
    """
    return TCP.send(conn,data)


def recv(conn: TCPConn, length: int) -> bytes:
    """
    bytes recibe a lo sumo `length` bytes almacenados en el buffer de la conexión.
    """
    return TCP.recv(conn, length)


def close(conn: Conn):
    """
    termina la conexión.
    """
    TCP.close_connection(conn)
