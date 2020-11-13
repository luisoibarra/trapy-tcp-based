# from trapy.socket_trapy import *
from trapy.tcp.trapy import *
from trapy.tcp.trapy import log
import trapy.utils as ut 
from threading import Thread
import socket

address = '127.0.0.2:6500'

TCP_layer = TCP()
TCP_layer.start()

def server_test():
    server = listen(address)
    client_con = accept(server)
    log.info("Server Done")
    data_recv = recv(client_con, 2048)
    log.info(f"Info received: {data_recv}")
    # close(server)
    # log.info("Server Closed")
    # data_sent = b'123456789a123456789b123456789c123456789d123456789e'
    # data_send_len = send(client_con, data_sent)
    # log.info(f"Server Sended: {data_send_len} of {len(data_sent)}")
    # data_sent = b'123456789a123456789b123456789c123456789d123456789e'
    # data_send_len = send(client_con, data_sent)
    # log.info(f"Server Sended: {data_send_len} of {len(data_sent)}")
    
    # data_recv = recv(client_con, 2048)
    # log.info(f"Info received: {data_recv}")
    # while data_recv:
    #     data_recv = recv(conn, 2048)
    #     log.info(f"Info received: {data_recv}")
    
    
    close(client_con)
    log.info("Client Server Closed")
    
def client_test():
    conn = dial(address)
    log.info("Client Done")
    data = b''
    data_send_len = send(conn, data)
    log.info(f"Client Sended: {data_send_len} of {len(data)}")
    
    # data_recv = recv(conn, 2048)
    # log.info(f"Info received: {data_recv}")
    # while data_recv:
    #     data_recv = recv(conn, 2048)
    #     log.info(f"Info received: {data_recv}")
    # data_sent = b'123456789a123456789b123456789c123456789d123456789e'
    # data_send_len = send(conn, data_sent)
    # log.info(f"Server Sended: {data_send_len} of {len(data_sent)}")
    
    
    # close(conn)
    # log.info("Client Closed")

def test_1():
    Thread(target=client_test, name='Client').start()
    Thread(target=server_test, name='Server').start()
    while True:
        pass

test_1()

def simple_transfer_test():
    host = '127.0.0.2'
    address1 = (host,65000)
    address2 = (host,65001)
    end1 = ut.get_raw_socket()
    # end1.bind(address1) # If binded the message is replaced by something else 
    end2 = ut.get_raw_socket(); # Can be replaced by => ut.get_recv_socket(host)
    end2.bind((host,1)) # The port it is not used, put anything but 0. Binding of IP level (Host)
    packet1 = ut.construct_packet("end1 -> end2".encode(),address1[0],address2[0],address1[1],address2[1],0,0)
    end1.sendto(packet1,('127.0.0.3',1234)) # An address must be provided although is not used
    raw_packet1 = end2.recv(1024)
    data, info = ut.deconstruct_packet(raw_packet1)
    print(data.decode())
    print(info)

# simple_transfer_test()

def listen_all():
    s = ut.get_raw_socket()
    s.bind(('',3112))
    while True:
        print(s.recvfrom(2048))

# listen_all()

import serve_file.__main__ as sf
def serve_file_client(server_ip, data_rcv_file):
    sf.make_client(server_ip, data_rcv_file)

def serve_file_server(server_ip, file_to_send, chunk_size):
    sf.make_server(server_ip, file_to_send, chunk_size)

def test_2():
    Thread(target=serve_file_server, args=(address, 'sent.txt',100), name='Server').start()
    Thread(target=serve_file_client, args=(address, 'recv.txt'), name='Client').start()
    while True:
        pass

# test_2()

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

def tcp_client():
    sock = s.socket()
    sock.connect(ut.parse_address(address))
    sock.send(b"Hello")
    sock.close()
    while True:
        pass

def tcp_server():
    sock = s.socket()
    sock.bind(ut.parse_address(address))
    sock.listen()
    conn, _ = sock.accept()
    print(_)
    data = True
    while data:
        data = conn.recv(1024)
        print(data)
        
def test_tcp():
    Thread(target=tcp_server, name='Server').start()
    time.sleep(1)
    Thread(target=tcp_client, name='Client').start()
    while True:
        pass

# test_tcp()