from trapy.trapy import *
from trapy.tcp.tcp_log import log
import trapy.utils as ut 
from threading import Thread
import socket

address = '127.0.0.2:6500'

class TCPNoACK(TCP):
    """
    TCP layer that not handle ACK packages
    """
    def _can_queue_data(self, pkg):
        if pkg.ack_flag:
            return None
        else:
            return pkg

TCP_layer = TCP() # Start TCP 
TCP_layer.start()

def server_test():
    server = listen(address)
    client_con = accept(server)
    log.info("Server Done")
    data_recv = None
    data = b""
    while True:
        try:
            data = recv(client_con, 2048)
        except Exception:
            break
        log.info(f"Server Recv {data}")
        if data_recv == None:
            data_recv = b""
        data_recv += data
        
    log.info(f"Server Received: {data_recv} length:{len(data_recv)}")
    close(server)
    close(client_con)
    log.info("Client Server Closed")
    
def client_test():
    conn = dial(address)
    log.info("Client Done")
    data = b'123456789a123456789b123456789c123456789d123456789e123456789f123456789g123456789h'
    data_send_len = send(conn, data)
    log.info(f"Client Sended: {data_send_len} of {len(data)}")
    close(conn)
    log.info("Client Closed")

def test_1():
    Thread(target=client_test, name='Client').start()
    Thread(target=server_test, name='Server').start()
    while True:
        pass

# test_1()

def my_send_data():
    conn = dial(address)
    data = b"123456789a123456789b123456789c123456789d123456789e123456789f123456789g"
    size = 10
    while data:
        pkg, data = data[:size], data[size:]
        len_send = send(conn, pkg)
        log.info(f"Sent {pkg[:len_send]}")
        data = pkg[len_send:] + data
    close(conn)

def my_recv_data():
    server = listen(address)
    conn = accept(server)
    close(server)
    data = b''
    rcv_data = True
    while rcv_data:
        rcv_data = recv(conn, 1)
        log.info(f"Received {rcv_data}")
        data += rcv_data
    log.info(f"Final data {data}")
    close(conn)

def test_3():
    Thread(target=my_recv_data, name='Server').start()
    Thread(target=my_send_data, name='Client').start()
    while True:
        pass

# test_3()
