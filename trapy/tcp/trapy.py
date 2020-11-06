from trapy.tcp.tcp import *

TCP_layer = TCP()
TCP_layer.start()

def listen(address: str) -> TCPConnServer:
    """
    prepara una conexión que acepta los paquetes enviados a `address`.
    """
    server = TCP_layer.start_server(address)
    return server


def accept(conn: TCPConnServer) -> TCPConn:
    """
    espera por alguna petición de conexión utilizando un `conn` creado previamente con `listen`.
    """
    conn.accepting = True
    while not conn.accepted_connections:
        pass # TODO Timer?
    conn.accepting = False
    return conn.accepted_connections.pop()


def dial(address:str) -> TCPConn:
    """
    establece conexión con el otro extremo indicado en `address` y devuelve la conexión.
    """
    return TCP_layer.start_connection(address)


def send(conn: TCPConn, data: bytes) -> int:
    """
    envía los datos por la conexión y devuelve la cantidad de bytes enviados.
    """
    pass


def recv(conn: TCPConn, length: int) -> bytes:
    """
    bytes recibe a lo sumo length bytes almacenados en el buffer de la conexión.
    """
    pass


def close(conn: Conn):
    """
    termina la conexión.
    """
    pass
