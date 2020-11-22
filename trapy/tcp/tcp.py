import trapy.utils as ut
from trapy.tcp.tcp_conn import Conn
from trapy.tcp.tcp_pkg import TCPPackage
from threading import Thread, Lock
from trapy.tcp.tcp_log import log
import random
import time

class ConnectionDict:
    """
    Dictionary that maps (source_host,source_port,destination_host,destination_port) to 
    its active Connection
    """
    def __init__(self, *args, **kwargs):
        self.conn_dict = dict() # local_host, local_port, dest_host, dest_port -> conn
        self.server_conn_dict = dict() # local_host, local_port -> conn
        
    def get(self, source_host:str, source_port:int, dest_host:str, dest_port:int) -> Conn:
        return self.conn_dict.get((source_host,source_port,dest_host,dest_port))
    
    def add(self, conn: Conn):
        source_host, source_port, dest_host, dest_port = conn.local_host, conn.local_port, conn.dest_host, conn.dest_port
        log.info(f"Connection added: {source_host}:{source_port} -> {dest_host}:{dest_port}")
        self.conn_dict[source_host,source_port,dest_host,dest_port] = conn
        
    def delete(self, source_host:str, source_port:int, dest_host:str, dest_port:int):
        log.info(f"Connection deleted: {source_host}:{source_port} -> {dest_host}:{dest_port}")
        self.conn_dict.pop((source_host, source_port, dest_host, dest_port),None)
        
    def add_server(self, conn: Conn):
        host, port = conn.local_host, conn.local_port
        log.info(f"Server Connection added: {host}:{port}")
        self.server_conn_dict[host,port] = conn
    
    def get_server(self, host:str, port:int) -> Conn:
        return self.server_conn_dict.get((host,port))
    
    def delete_server(self, host:str, port:int):
        log.info(f"Server Connection deleted: {host}:{port}")
        self.server_conn_dict.pop((host, port),None)

class TCP:
    """
    Virtual Transport TCP Layer
    """
    
    # Socket that receive all packages
    recv_sock = ut.get_raw_socket()
    
    # All TCP connections
    conn_dict = ConnectionDict()
    
    def __init__(self, host:str="", *args, **kwargs):
        # self.recv_sock.bind(('',0)) # Receive all connections
        self.recv_sock.bind((host,0))
        self.__running = False

    def start(self):
        """
        Start the TCP functionality.  
        Must be called before any other method
        """
        if not self.__running:
            self.__running = True
            self.recv_thread = Thread(target=self.demultiplex, name='TCP', daemon=True)
            self.recv_thread.start()
            log.info("TCP Started")
    
    def wait(self):
        """
        Wait for TCP to stop running
        """
        while self.__running:
            time.sleep(2)
    
    def end(self):
        """
        Release all TCP resources and close all connections
        """
        if self.__running:
            self.close_all()
            self.__running = False
            self.recv_thread.join(2)
            self.recv_sock.close()
            log.info("TCP Closed")
    
    def demultiplex(self):
        """
        Redirects incoming packages to corresponding connection
        """
        while self.__running:
            data = self.recv_sock.recv(2048)
            package = TCPPackage(data)
            package = self._can_queue_data(package):
            if package:
                log.info(f"TCP recv package: {package._info()}")
                conn = self.conn_dict.get(package.dest_host, package.dest_port,
                                          package.source_host, package.source_port)
                server_conn = self.conn_dict.get_server(package.dest_host,package.dest_port)
                if conn:
                    conn.handle_pkg(package)
                elif server_conn and package.syn_flag:
                    conn = server_conn.server_handle_pkg(package)
                    if conn:
                        TCP.add_connection(conn)
                # elif not package.rst_flag: # When several TCP instances are running comment this
                #     self._send_no_conn_reply(package)
                
    @staticmethod
    def start_server(address:str) -> Conn:
        """
        return a working TCPConnServer binded to `address`
        """
        host, port = ut.parse_address(address)
        conn = Conn(host,port,None,None, TCP)
        TCP.add_connection(conn)
        conn.init_server()
        return conn
    
    @staticmethod
    def start_connection(address:str) -> Conn:
        """
        return a `Conn` connected to address
        """
        local_host, local_port = TCP._get_address()
        dest_host, dest_port = ut.parse_address(address)
        conn = Conn(local_host, local_port, dest_host, dest_port, TCP)
        TCP.add_connection(conn)
        conn.init_connection()
        while conn.state != Conn.CONNECTED:
            time.sleep(0.3)
            pass # TODO Timer?
        return conn
        
    @staticmethod
    def add_connection(conn:Conn):
        if conn.is_server:
            TCP.conn_dict.add_server(conn)
        else:
            TCP.conn_dict.add(conn)
    
    @staticmethod
    def remove_connection(conn:Conn):
        if conn.is_server:
            TCP.conn_dict.delete_server(conn.local_host, conn.local_port)
        else:
            TCP.conn_dict.delete(conn.local_host, conn.local_port, conn.dest_host, conn.dest_port)
    
    @staticmethod
    def close_connection(conn:Conn):
        conn.close()
        while not conn.is_closed:
            pass # TODO <- Timer?
    
    @staticmethod
    def accept(conn:Conn):
        conn._accepting(True)
        accepted_conn = conn.get_accepted_conn()
        while not accepted_conn:
            # TODO <- Timer?
            time.sleep(0.3)
            accepted_conn = conn.get_accepted_conn()
        conn._accepting(False)
        return accepted_conn
    
    @staticmethod
    def send(conn:Conn, data:bytes):
        return conn.send(data)
    
    @staticmethod
    def recv(conn:Conn, length:int):
        data = None
        while data == None:
            data = conn.dump(length)
            time.sleep(0.1)
        return data
    
    def _can_queue_data(self, pkg:TCPPackage) -> TCPPackage:
        """
        returns the `TCPPackage` to be handled by the connections from `pkg`
        """
        # if random.choice([True, False]): # Simulate unreliable transport medium
        #     return pkg
        # return None
        if not pkg.corrupted:
            return pkg
    
    def _send_no_conn_reply(self, package:TCPPackage):
        """
        Send a rst package to client
        """
        with ut.get_raw_socket() as s:
            # Change package information
            # Set rst flag to notify that no conn exist with the package address
            flags = ut.PacketFlags(False, True, False, False, False, False, False, False)
            info = ut.PacketInfo(package.dest_host, package.source_host, package.dest_port,
                                 package.source_port, package.ack_number, package.seq_number,0,
                                 flags, 0, package.window_size)
            package = TCPPackage(b"", info, True)
            s.sendto(package.to_bytes(),(package.dest_host, package.dest_port))
            log.info(f"RST Package sent {package._endpoint_info()}")
    
    def close_all(self):
        keys = [x for x in self.conn_dict.server_conn_dict]
        for key in keys:
            conn = self.conn_dict.server_conn_dict[key]
            conn._close_connection(0)
        keys = [x for x in self.conn_dict.conn_dict]
        for key in keys:
            conn = self.conn_dict.conn_dict[key]
            conn._close_connection(0)
    
    @staticmethod
    def _get_address() -> (str,int):
        """
        return the initial address of a new TCPConn
        """
        return ('127.0.0.2', random.randint(1024, (1<<16)-1)) # TODO Change host and port generator 
