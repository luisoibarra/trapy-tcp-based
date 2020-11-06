import socket as s
import trapy.utils as ut
from trapy.timer import Timer
import random
import time
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, Future

class TCPPackage:
    
    def __init__(self, data:bytes, info:ut.PacketInfo=None):
        if not info:
            data, info = ut.deconstruct_packet(data)
        self.dest_host = info.dest_host
        self.dest_port = info.dest_port
        self.source_host = info.source_host
        self.source_port = info.source_port
        self.checksum = info.checksum
        self.seq_number = info.seq_number
        self.ack_number = info.ack_number
        self.ack_flag = info.flags.ack
        self.syn_flag = info.flags.syn
        self.fin_flag = info.flags.fin
        self.rst_flag = info.flags.rst
        self.data = data
    
    def _get_packet(self)->ut.PacketInfo:
        packet = ut.PacketInfo(self.source_host, self.dest_host, self.source_port,
                        self.dest_port, self.seq_number, self.ack_number, self.checksum,
                        ut.PacketFlags(self.ack_flag, self.rst_flag, self.syn_flag,self.fin_flag))
        return packet
    
    def to_bytes(self):
        packet = self._get_packet()
        return ut.construct_packet(self.data, packet)

    def copy(self) -> 'TCPPackage':
        packet = self.to_bytes()
        return TCPPackage(packet)

    def swap_endpoints(self):
        self.source_port, self.source_host, self.dest_port, self.dest_host = self.dest_port, self.dest_host, self.source_port, self.source_host 

class Sender:
    
    def send(self, packets:list, seq_number:int, **kwargs) -> Future:
        self.to_send = packets
        self.acks = []
        self.base = 0
        self.base_seq = seq_number
        self.send_sock = ut.get_raw_socket()
        self.window_size = kwargs.get('window_size',1)
        self.next_to_send = 0
        self.timer = Timer(kwargs.get('timeout',0.5))
        sending_future = ThreadPoolExecutor(max_workers=1)
        return sending_future.submit(self._send)
    
    def _send(self):
        while self.base < len(self.to_send):
            window_end = min(self.base+self.window_size, len(self.to_send))
            while self.next_to_send < window_end:
                pkg = self.to_send[self.next_to_send]
                self.send_sock.sendto(pkg.to_bytes(), (pkg.dest_host, pkg.dest_port))
                self.next_to_send += 1
            
            if not self.timer.running():
                self.timer.start()

            while self.timer.running() and not self.timer.timeout():
                time.sleep(0.05)
            
            if self.timer.timeout():
                self.next_to_send = self.base
                self.timer.stop()
            else:
                self.base = self.next_to_send
                self.window_size = min(self.window_size, len(self.to_send) - self.base)

    def ack_package(self, ack:int):
        ack = ack - self.base_seq
        self.base = max(ack, self.base)
        if ack == self.base - 1:
            self.timer.stop()

class Conn:
    """
    Base Conn class
    """
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        self.local_host = host
        self.local_port = port
        
        self.in_buffer = []
        # self.out_buffer = [] # TODO DEPRECATED
        self.seq_number = 0 # random.randint(0,(1<<32)-1)
        self.base_number = None
        self.window_size = None
        
        self.sock = ut.get_raw_socket()
        self.recv_thread = Thread(target=self.conn_run)
        self.sender = Sender()
        self.sender_task = None

    def add_package(self, package:TCPPackage):
        """
        Add packages to the connection in buffer 
        """
        self.in_buffer.append(package)
        
    def start(self):
        """
        Start current connection
        """
        self.recv_thread.start()
  
    def conn_run(self):
        while True:
            package = self._recv()
            if package.rst_flag:
                self.handle_rst_package(package)
            if package.syn_flag:
                self.handle_syn_package(package)
            if package.ack_flag:
                self.handle_ack_package(package)
  
    def handle_syn_package(self, package:TCPPackage):
        raise NotImplementedError()
        
    def handle_ack_package(self, package:TCPPackage):
        # self._remove_acked_packages(package.ack_number)
        if self.sender_task and self.sender_task.running():
            self.sender.ack_package(package.ack_number)
    
    def handle_rst_package(self, package:TCPPackage):
        raise NotImplementedError() 
    
    def _use_seq_number(self, times=1):
        number = self.seq_number
        self.seq_number = ut.next_number(self.seq_number, times)
        return number
       
    def _recv(self):
        while True:
            if self.in_buffer:
                return self.in_buffer.pop(0)
    
    def _send(self, send_package:TCPPackage):
        # self.out_buffer.append(send_package)
        self.sender_task = self.sender.send([send_package], self.seq_number)

    # TODO DEPREATED #
    def _remove_acked_packages(self, ack:int):
        """
        Remove the acked packages from `out_buffer`  
        `ack`: package ack number
        """
        if ack < self.base_number:
            if self.base_number > self.seq_number and ack < self.seq_number:
                # acking a package that started from 0
                self._remove_acked_packages((1<<32)-1)
            else:
                # acking an invalid pkg 
                return
            
        # From here self.base_number <= self.seq_number
        if ack > self.seq_number:
            # acking not sended pkg
            return
        
        to_remove = []
        for pkg in self.out_buffer:
            if pkg.seq_number <= ack:
                to_remove.append(pkg)
        
        for pkg in to_remove:
            self.out_buffer.remove(pkg)
            
        self.base_number = ut.next_number(ack)
    def conn_send(self):
        while True:
            if self.out_buffer:
                while self.out_buffer:
                    self.sock.sendto(send_package.to_bytes(),(send_package.dest_host, send_package.dest_port))
                    time.sleep(1)             
    # END DEPRECATED#
            
class ConnException(Exception):
    """
    Base Connection Exception
    """
    pass

class TCPConn(Conn):
    """
    Hold the non server connection state 
    """
    def __init__(self, host:str, port:int, *args, **kwargs):
        super().__init__(host, port, *args, **kwargs)
        self.dest_host = None
        self.dest_port = None
        self.connected = False
   
    def handle_rst_package(self, package: TCPPackage):
        raise ConnException(f"Connection doesnt exist {package.dest_host}:{package.dest_port}")
   
    # Handshake    
    def init_connection(self, address:str):
        """
        Send SYN package to `address`
        """
        host, port = ut.parse_address(address)
        self.dest_host = host
        self.dest_port = port
        syn_package = TCPPackage(b'',ut.PacketInfo(self.local_host,self.dest_host,self.local_port,
                                                   self.dest_port, self._use_seq_number(), 0, 0, 
                                                   ut.PacketFlags(False, False, True, False)))
        self._send(syn_package)
        
    def handle_syn_package(self, package:TCPPackage):
        if not self.connected:
            self.ack_server_handshake(package)
        
    def ack_server_handshake(self, server_package:TCPPackage):
        """
        Acknowledge the handshake message (`server_package`) from client  
        Prepare the current connection to send-receive process
        """
        if server_package.ack_flag and server_package.ack_number == self.seq_number:
            # Get endpoint port
            conn_port = ut.get_int_of(server_package.data)
            
            # Build send package
            response = server_package.copy()
            response.swap_endpoints()
            response.syn_flag = False
            response.seq_number = self._use_seq_number()
            response.ack_number = ut.next_number(server_package.seq_number)
            
            # Send package
            self._send(response)
            
            # Update connection state
            TCP.remove_connection(self)
            self.dest_port = conn_port
            TCP.add_connection(self)
            self.connected = True
    ##

class TCPConnServer(Conn):
    """
    Hold the server connection state 
    """
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        super().__init__(host, port, *args, **kwargs)
        self.accepting = False
        self.accepted_connections = []
        self.pending_ack_conn = dict() # host,port -> expected_ack_number, TCPConn
    
    def handle_rst_package(self, package:TCPPackage):
        self.pending_ack_conn.pop((package.source_host, package.source_port),None)
    
    # Handshake   
    def handle_syn_package(self, package:TCPPackage):
        if self.accepting:
            key = package.source_host, package.source_port
            if key in self.pending_ack_conn:
                # TODO The client resend initial syn package
                pass
            else:
                self.response_handshake(package)
            
    def handle_ack_package(self, package:TCPPackage):
        """
        Final step of the handshake
        """
        super().handle_ack_package(package)
        key = package.source_host, package.source_port
        expected_ack, conn = self.pending_ack_conn.pop(key,(None,None))
        if conn and expected_ack == package.ack_number:
            conn.connected = True
            TCP.add_connection(conn)
            self.accepted_connections.append(conn)
            conn.start()

    def response_handshake(self, initial_package:TCPPackage):
        """
        Sends server synack package of the handshake initiated by `initial_package`
        """
        # Create Connection
        conn = TCPConn(initial_package.dest_host, self._get_port())
        conn.dest_host = initial_package.source_host
        conn.dest_port = initial_package.source_port
        
        # Create package
        send_package = initial_package.copy()
        send_package.swap_endpoints()
        send_package.ack_flag = True
        send_package.ack_number = ut.next_number(initial_package.seq_number)
        send_package.seq_number = self._use_seq_number()
        
        # Attach the new created port number 
        send_package.data = ut.get_byte_of(conn.local_port, 2)
        
        # Save conn to last ack packet
        self.pending_ack_conn[send_package.dest_host,send_package.dest_port] = ut.next_number(send_package.seq_number),conn
        
        # Send package
        self._send(send_package)
         
    def _get_port(self):
        """
        Get port for new connection created by server
        """
        return random.randint(1024, (1<<16)-1)

class ConnectionDict:
    """
    Dictionary that maps (source_host,source_port,destination_host,destination_port) to 
    its active Connection
    """
    def __init__(self, *args, **kwargs):
        self.conn_dict = dict()
        self.server_conn_dict = dict()
        
    def get(self, source_host:str, source_port:int, dest_host:str, dest_port:int) -> TCPConn:
        return self.conn_dict.get((source_host,source_port,dest_host,dest_port))
    
    def add(self, source_host:str, source_port:int, dest_host:str, dest_port:int, conn: TCPConn):
        self.conn_dict[source_host,source_port,dest_host,dest_port] = conn
        
    def delete(self, source_host:str, source_port:int, dest_host:str, dest_port:int):
        self.conn_dict.pop((source_host, source_port, dest_host, dest_port),None)
        
    def add_server(self, host:str, port:int, conn: TCPConnServer):
        self.server_conn_dict[host,port] = conn
    
    def get_server(self, host:str, port:int) -> TCPConnServer:
        return self.server_conn_dict.get((host,port))
    
    def delete_server(self, host:str, port:int):
        self.server_conn_dict.pop((host, port),None)

class TCP:
    """
    Virtual Transport TCP Layer
    """
    # Socket that receive all packages
    recv_sock = ut.get_raw_socket()
    
    # All TCP connections
    conn_dict = ConnectionDict()
    
    def __init__(self, *args, **kwargs):
        # self.recv_sock.bind(('',0)) # Receive all connections 
        self.recv_sock.bind(('127.0.0.2',0)) # Receive all connections 
        self.recv_thread = Thread(target=self.demultiplex, daemon=True)

    def start(self):
        """
        Start the TCP functionality.  
        Must be called before any other method
        """
        self.recv_thread.start()
    
    def demultiplex(self):
        """
        Redirects incoming packages to corresponding connection
        """
        while True:
            data = self.recv_sock.recv(2048)
            if self._can_queue_data(data):
                package = TCPPackage(data)
                conn = self.conn_dict.get(package.dest_host, package.dest_port,
                                          package.source_host, package.source_port)
                server_conn = self.conn_dict.get_server(package.dest_host,package.dest_port)
                if conn:
                    conn.add_package(package)
                if server_conn:
                    server_conn.add_package(package)
                if not conn and not server_conn:
                    self._send_no_conn_reply(package)
                
    def start_server(self, address:str) -> TCPConnServer:
        """
        return a working TCPConnServer binded to `address`
        """
        host, port = ut.parse_address(address)
        conn = TCPConnServer(host,port)
        self.conn_dict.add_server(host, port, conn)
        conn.start()
        return conn
    
    def start_connection(self, address:str) -> TCPConn:
        """
        return a TCPConn connected to address
        """
        conn = TCPConn(*self._get_address())
        conn.dest_host, conn.dest_port = ut.parse_address(address)
        conn.start()
        TCP.add_connection(conn)
        conn.init_connection(address)
        while not conn.connected:
            pass # TODO Timer?
        return conn
        
    @staticmethod
    def add_connection(conn:Conn):
        if isinstance(conn, TCPConnServer):
            TCP.conn_dict.add_server(conn)
        else:
            TCP.conn_dict.add(conn.local_host, conn.local_port, conn.dest_host, conn.dest_port, conn)
    
    @staticmethod
    def remove_connection(conn:Conn):
        if isinstance(conn, TCPConnServer):
            TCP.conn_dict.delete_server(conn.local_host, conn.local_port)
        else:
            TCP.conn_dict.delete(conn.local_host, conn.local_port, conn.dest_host, conn.dest_port)
            
    def _can_queue_data(self, data:bytes):
        """
        returns if the data must be queued in the `in_buffer`
        """
        return True
    
    def _send_no_conn_reply(self, package:TCPPackage):
        """
        Send a rst package to client
        """
        with ut.get_raw_socket() as s:
            # Change package information
            package.swap_endpoints()
            # Set rst flag to notify that no conn exist with the package address
            package.rst_flag = True
            package.seq_number, package.ack_number = package.ack_number, package.seq_number
            s.sendto(package.to_bytes(),(package.source_host, package.source_port))
    
    def _get_address(self) -> (str,int):
        """
        return the initial address of a new TCPConn
        """
        return ('127.0.0.2', random.randint(1024, (1<<16)-1))
