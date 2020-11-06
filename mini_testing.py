# from trapy.udp_trapy.udp_trapy import *
# from trapy.my_trapy.trapy import *
from trapy.tcp.trapy import *
import trapy.utils as ut 
from threading import Thread
import socket

address = '127.0.0.2:6500'

def server_test():
    server = listen(address)
    client_con = accept(server)
    print("Server Done")
    # data_recv = recv(client_con, 2048)
    # print(data_recv)
    # data_send_len = send(client_con, b'Hello sending data from server to client')
    # close(client_con)
    # close(server)
    
def client_test():
    server_con = dial(address)
    print("Client Done")
    # data_send_len = send(server_con, b'Hello sending data from client to server')
    # data_recv = recv(server_con, 2048)
    # print(data_recv)
    # close(server_con)

Thread(target=client_test).start()
Thread(target=server_test()).start()

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