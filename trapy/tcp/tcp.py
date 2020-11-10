import socket as s
import trapy.utils as ut
from trapy.timer import Timer
import random
import time
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, Future
import logging as log
log.basicConfig(level=log.DEBUG, format='[%(asctime)s] %(levelname)s - %(message)s')

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
        self.urg_ptr = info.urg_ptr
        self.data = data
    
    def _get_packet(self)->ut.PacketInfo:
        packet = ut.PacketInfo(self.source_host, self.dest_host, self.source_port,
                        self.dest_port, self.seq_number, self.ack_number, self.checksum,
                        ut.PacketFlags(self.ack_flag, self.rst_flag, self.syn_flag,self.fin_flag),
                        self.urg_ptr)
        return packet
    
    @property
    def no_flag(self)->bool:
        return not self.fin_flag and not self.ack_flag and not self.rst_flag and not self.syn_flag
    
    def to_bytes(self):
        packet = self._get_packet()
        return ut.construct_packet(self.data, packet)

    def copy(self) -> 'TCPPackage':
        packet = self.to_bytes()
        return TCPPackage(packet)

    def swap_endpoints(self):
        self.source_port, self.source_host, self.dest_port, self.dest_host = self.dest_port, self.dest_host, self.source_port, self.source_host 

    def _info(self):
        address = f"{self.source_host}:{self.source_port}->{self.dest_host}:{self.dest_port}" 
        pkg_num = f"SEQ#:{self.seq_number} ACK#:{self.ack_number}"
        flags = f"[{''.join(['ACK' if self.ack_flag else '', ' RST' if self.rst_flag else '', ' SYN' if self.syn_flag else '', ' FIN' if self.fin_flag else '' ])}]"
        return f"{address} {pkg_num} {flags}"

class Sender:
    
    DEFAULT_TIMEOUT = 1
    DEFAULT_WINDOW_SIZE = 1
    
    def __init__(self, *args, **kwargs):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.send_sock = ut.get_raw_socket()
        self.timer = None
        self.sender_task = None
        self.__running = False
    
    def no_ack_send(self, packages:list):
        for pkg in packages:
            self.send_sock.sendto(pkg.to_bytes(), (pkg.dest_host, pkg.dest_port))
    
    def send(self, packets:list, seq_number:int, **kwargs) -> Future:
        self.to_send = packets
        self.acks = []
        self.base = 0
        self.base_seq = seq_number
        self.window_size = kwargs.get('window_size',self.DEFAULT_WINDOW_SIZE)
        self.next_to_send = 0
        self.timer = Timer(kwargs.get('timeout',self.DEFAULT_TIMEOUT))
        self.__running = True
        self.sender_task = self.executor.submit(self._send)
        return self.sender_task
    
    def _send(self):
        while self.__running and self.base < len(self.to_send):
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
        if ack == self.base:# - 1:
            self.timer.stop()

    def close(self):
        timer = Timer(10)
        timer.start()
        while not timer.timeout() and self.sender_task and self.sender_task.running():
            time.sleep(0.5)
        self.__running = False
        if self.timer:
            self.timer.stop()
        self.executor.shutdown()

class BatchPackageBuilder:
    """
    Build packages for the associated Conn instance  
    Handling flow control <- TODO this can be done by passing extra info when building packages or by putting this info in the conn instance 
    """
    
    def __init__(self, conn:'TCPConn'):
        self.__conn = conn
    
    def build_packages(self, data:bytes, max_pkg_size:int=1460, max_amount:int=-1):
        """
        Build a list of packages of sizes <= `max_pkg_size`  
        The length of the list is <= `max_amount` in case of `max_amount` > 0  
        return remaining_data,packages 
        """
        max_amount = max_amount if max_amount > 0 else (1<<32)-1
        info = ut.PacketInfo(self.__conn.local_host,self.__conn.dest_host,self.__conn.local_port,
                            self.__conn.dest_port, self.__conn._use_seq_number(),self.__conn.ack_number,0,
                            ut.PacketFlags(False, False, False, False),0)
        packages = []
        while data and len(packages) < max_amount:
            pkg, data = data[:max_pkg_size], data[max_pkg_size:]
            package = TCPPackage(pkg,info)
            packages.append(package)
            info = ut.PacketInfo(self.__conn.local_host,self.__conn.dest_host,self.__conn.local_port,
                                self.__conn.dest_port, self.__conn._use_seq_number(),self.__conn.ack_number,0,
                                ut.PacketFlags(False, False, False, False),0)
        packages.append(TCPPackage(b'',info)) # Add last package package
        return packages, data
    
class Conn:
    """
    Base Conn class
    """
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        self.local_host = host
        self.local_port = port
        
        self.in_buffer = []
        self.base_seq_number = 0 # random.randint(0,(1<<32)-1) # initial seq number
        self.seq_number = self.base_seq_number # current seq_number
        
        self.sock = ut.get_raw_socket() # sending_socket
        self.recv_executor = ThreadPoolExecutor(max_workers=1)
        self.recv_task = None
        self.sender = Sender()
        self.sender_task = None
        
        self.__running = False

    def add_package(self, package:TCPPackage):
        """
        Add packages to the connection in buffer 
        """
        self.in_buffer.append(package)
    
    @property
    def is_running(self):
        return self.recv_task and self.recv_task.running()
    
    def start(self):
        """
        Start current connection
        """
        self.__running = True
        self.recv_task = self.recv_executor.submit(self.conn_run)
  
    def conn_run(self):
        while self.__running:
            package = self._recv()
            if package.ack_flag:
                self.handle_ack_package(package)
            if package.fin_flag:
                self.handle_fin_package(package)
            if package.rst_flag:
                self.handle_rst_package(package)
            if package.syn_flag:
                self.handle_syn_package(package)
            if package.no_flag:
                self.handle_no_flag_package(package)

    def handle_fin_package(self, package:TCPPackage):
        raise NotImplementedError()
    
    def handle_syn_package(self, package:TCPPackage):
        raise NotImplementedError()
        
    def handle_ack_package(self, package:TCPPackage):
        if self.sender_task: #and self.sender_task.running(): # A Pending state also exist
            self.sender.ack_package(package.ack_number)
    
    def handle_rst_package(self, package:TCPPackage):
        raise NotImplementedError() 
    
    def handle_no_flag_package(package):
        raise NotImplementedError()
    
    def _use_seq_number(self, times=1):
        number = self.seq_number
        self.seq_number = ut.next_number(self.seq_number, times)
        return number
   
    def _recv(self):
        while self.__running:
            self._watch_function()
            if self.in_buffer:
                return self.in_buffer.pop(0)
    
    def _watch_function(self):
        """
        Function called to verify time events
        """
        pass
    
    def _send(self, send_package:TCPPackage, need_ack=True):
        """
        Send the `send_package`  
        if `need_ack` then its sended in a reliable way else its just sended
        """
        log.info(f"Package send scheduled: {send_package._info()}")
        if need_ack:
            self.sender_task = self.sender.send([send_package], self.seq_number)
        else:
            self.sender.no_ack_send([send_package])

    def _release_resources(self):
        """
        Release all resources related to this conenction
        """
        self.sender.close()
        TCP.remove_connection(self)
        self.__running = False
        self.connected = False
        self.recv_executor.shutdown()
    
    def _ack_package(self, package:TCPPackage):
        """
        Send an ack package of `package`
        """
        ack_pkg = package.copy()
        ack_pkg.swap_endpoints()
        ack_pkg.ack_flag = True
        ack_pkg.data = b''
        ack_pkg.fin_flag = ack_pkg.syn_flag = ack_pkg.rst_flag = False
        ack_pkg.ack_number, ack_pkg.seq_number = self.ack_number, self.seq_number
        self._send(ack_pkg, False)
        
    def close(self):
        """
        Start the closing stage of the connection 
        """
        raise NotImplementedError()
    
class ConnException(Exception):
    """
    Base Connection Exception
    """
    pass

class TCPConn(Conn):
    """
    Hold the non server connection state 
    """
    
    FIN_WAITING = 5 # Time to wait for connection to close
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        super().__init__(host, port, *args, **kwargs)
        self.base_ack_number = None # Initial other side seq_number
        self.ack_number = self.base_ack_number # expected byte from other side
        self.dest_host = None
        self.dest_port = None
        self.connected = False
        self.sended_fin = None
        self.responded_fin = None
        self.in_package_data = dict() # seq_number -> data
        self.dump_buffer = b''
        self.heavy_sender = Sender()
        self.heavy_sender_task = None
        self.builder = BatchPackageBuilder(self)
        self.fin_timer = Timer(self.FIN_WAITING)

    def handle_rst_package(self, package: TCPPackage):
        pass

    def handle_ack_package(self, package:TCPPackage):
        self._update_ack(package)
        super().handle_ack_package(package)
        if self.responded_fin and package.seq_number >= self.responded_fin.ack_number: # if the responded_fin pkg was acked
            self._release_resources()
        elif self.heavy_sender_task and self.heavy_sender_task.running():
            self.heavy_sender.ack_package(package.ack_number)
    
    def handle_no_flag_package(self, package:TCPPackage):
        if self.connected:
            self.in_package_data[package.seq_number] = package.data
            self._ack_package(package)

    def send(self, data:bytes):
        init_length = len(data)
        if self.heavy_sender_task and self.heavy_sender_task.running():
            raise ConnException("Already sending data")
        while data:
            packages, data = self.builder.build_packages(data)
            self.heavy_sender_task = self.heavy_sender.send(packages, packages[0].seq_number)
            while self.heavy_sender_task.running():
                time.sleep(0.1)
        return init_length
    
    def dump(self, length:int):
        """
        return the received data up to `length` bytes
        """
        if self.dump_buffer and len(self.dump_buffer) >= length:
            data, self.dump_buffer = self.dump_buffer[:length], self.dump_buffer[length:]
            return data
        
        if self.in_package_data:
            # TODO This is not reliable because i dont know which is the first package
            keys = list(self.in_package_data.keys())
            keys.sort()
            to_dump = b''
            end_msg = False # Empty msg received
            
            # do
            iter_keys = iter(keys)
            prev_key = next(iter_keys)
            data = self.in_package_data.pop(prev_key)
            to_dump += data
            end_msg |= bool(data)
            for i,key in enumerate(iter_keys,1): # while
                if end_msg:
                    break
                # Successive packages
                if key == prev_key + 1:
                    data = self.in_package_data.pop(key)
                    to_dump += data
                    end_msg |= bool(data)
                    prev_key = key
                else:
                    break
            self.dump_buffer += to_dump
            data, self.dump_buffer = self.dump_buffer[:length], self.dump_buffer[length:]
            return data
            
    
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
                                                   ut.PacketFlags(False, False, True, False),0))
        self._send(syn_package)
        
    def handle_syn_package(self, package:TCPPackage):
        if not self.connected:
            # Set other endpoint variables
            self.base_ack_number = package.seq_number
            self.ack_number = ut.next_number(package.seq_number)
            self.ack_server_handshake(package)
        
    def ack_server_handshake(self, server_package:TCPPackage):
        """
        Acknowledge the handshake message (`server_package`) from client  
        Prepare the current connection to send-receive process
        """
        if server_package.ack_flag and server_package.ack_number == self.seq_number:
            # Get endpoint port
            conn_port = server_package.urg_ptr
            
            # Build send package
            response = server_package.copy()
            response.swap_endpoints()
            response.syn_flag = False
            response.seq_number = self._use_seq_number()
            response.ack_number = self.ack_number
            
            # Send package
            self._send(response, False)
            
            # Update connection state
            TCP.remove_connection(self)
            self.dest_port = conn_port
            TCP.add_connection(self)
            self.connected = True
    ##
    
    # End Connection
    def handle_fin_package(self, package:TCPPackage):
        if not self.sended_fin:
            # fin received from other endpoint
            
            # Send fin ack
            if not self.responded_fin:
                self.responded_fin = ut.PacketInfo(self.local_host, self.dest_host, self.local_port,
                                            self.dest_port, self._use_seq_number(), self.ack_number, 0, 
                                            ut.PacketFlags(True, False, False, True),0)
            self._send(TCPPackage(b'',self.responded_fin))
            
        elif package.ack_flag:
            # fin received from other endpoint that received this peer fin package 
            # import time
            # time.sleep(15) # Waiting
            if not self.fin_timer.running():
                self.fin_timer.start()
                self._ack_package(package)
            elif not self.fin_timer.timeout():
                self._ack_package(package)
    
    def close(self):
        """
        Start the closing process by sending a FIN pkg
        """
        if self.connected:
            self.sended_fin = ut.PacketInfo(self.local_host, self.dest_host, self.local_port,
                                        self.dest_port, self._use_seq_number(), self.ack_number, 0, 
                                        ut.PacketFlags(False, False, False, True),0)
            
            self._send(TCPPackage(b'',self.sended_fin))
        else:
            self._release_resources()
    ##
    
    def _update_ack(self, package:TCPPackage):
        """
        Update the ack given a package
        """
        if self.ack_number == package.seq_number:
            self.ack_number = ut.next_number(self.ack_number,len(package.data) if package.data else 1) 

    def _watch_function(self):
        super()._watch_function()
        if self.fin_timer.timeout():
            self._release_resources()
    
    def _release_resources(self):
        self.heavy_sender.close()
        super()._release_resources()

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
    
    def handle_fin_package(sef, package:TCPPackage):
        pass
    
    def handle_no_flag_package(package):
        pass
    
    # Handshake   
    def handle_syn_package(self, package:TCPPackage):
        if self.accepting:
            key = package.source_host, package.source_port
            if key in self.pending_ack_conn:
                # TODO The client resend initial syn package
                _, conn = self.pending_ack_conn[key]
                resend_package = self._build_synack_package(package, conn.seq_number, conn.local_port) 
                self._send(resend_package)
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
            TCP.conn_dict.delete(self.local_host, self.local_port, package.source_host, package.source_port)
            conn.connected = True
            conn.seq_number = package.ack_number
            conn.ack_number = ut.next_number(package.seq_number)
            TCP.add_connection(conn)
            self.accepted_connections.append(conn)
            conn.start()

    def response_handshake(self, initial_package:TCPPackage):
        """
        Sends server synack package of the handshake initiated by `initial_package`
        """
        # Create This Connection
        TCP.conn_dict.add(self.local_host, self.local_port, 
                          initial_package.source_host, initial_package.source_port, self)
        
        # Create New Connection
        conn = TCPConn(initial_package.dest_host, self._get_port())
        conn.dest_host = initial_package.source_host
        conn.dest_port = initial_package.source_port
        conn.base_ack_number = initial_package.seq_number
        conn.ack_number = initial_package.seq_number
        
        # Create package
        send_package = self._build_synack_package(initial_package, conn.seq_number, conn.local_port)
        
        # Save conn to last ack packet
        self.pending_ack_conn[send_package.dest_host,send_package.dest_port] = ut.next_number(send_package.seq_number),conn
        
        # Send package
        self._send(send_package)
    
    def close(self):
        self._release_resources()
    
    def _build_synack_package(self, syn_package:TCPPackage, conn_seq_number:int, conn_port:int):
        # Create package
        send_package = syn_package.copy()
        send_package.swap_endpoints()
        send_package.ack_flag = True
        send_package.ack_number = ut.next_number(syn_package.seq_number)
        send_package.seq_number = conn_seq_number
        
        # Attach the new created port number 
        send_package.urg_ptr = conn_port
        return send_package
        
    
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
        self.conn_dict = dict() # local_host, local_port, dest_host, dest_port -> conn
        self.server_conn_dict = dict() # local_host, local_port -> conn
        
    def get(self, source_host:str, source_port:int, dest_host:str, dest_port:int) -> TCPConn:
        return self.conn_dict.get((source_host,source_port,dest_host,dest_port))
    
    def add(self, source_host:str, source_port:int, dest_host:str, dest_port:int, conn: TCPConn):
        log.info(f"Connection added: {source_host}:{source_port} -> {dest_host}:{dest_port}")
        self.conn_dict[source_host,source_port,dest_host,dest_port] = conn
        
    def delete(self, source_host:str, source_port:int, dest_host:str, dest_port:int):
        log.info(f"Connection deleted: {source_host}:{source_port} -> {dest_host}:{dest_port}")
        self.conn_dict.pop((source_host, source_port, dest_host, dest_port),None)
        
    def add_server(self, host:str, port:int, conn: TCPConnServer):
        log.info(f"Server Connection added: {host}:{port}")
        self.server_conn_dict[host,port] = conn
    
    def get_server(self, host:str, port:int) -> TCPConnServer:
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
    
    def __init__(self, *args, **kwargs):
        # self.recv_sock.bind(('',0)) # Receive all connections 
        self.recv_sock.bind(('127.0.0.2',0)) # TODO Non Production Bind Address
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
                log.info(f"TCP recv package: {package._info()}")
                conn = self.conn_dict.get(package.dest_host, package.dest_port,
                                          package.source_host, package.source_port)
                server_conn = self.conn_dict.get_server(package.dest_host,package.dest_port)
                if conn:
                    conn.add_package(package)
                elif server_conn and package.syn_flag:
                    server_conn.add_package(package)
                elif not package.rst_flag:
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
    
    @staticmethod
    def close_connection(conn:Conn):
        conn.close()
        while conn.is_running:
            pass
    
    @staticmethod
    def recv(conn:TCPConn, length:int):
        while not conn.in_package_data:
            time.sleep(0.5)
        return conn.dump(length)
    
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
            package.ack_flag = True
            package.fin_flag = False
            package.syn_flag = False
            package.seq_number, package.ack_number = package.ack_number, ut.next_number(package.seq_number)
            s.sendto(package.to_bytes(),(package.source_host, package.source_port))
            log.info(f"RST Package sent to {(package.source_host, package.source_port)}")
    
    def _get_address(self) -> (str,int):
        """
        return the initial address of a new TCPConn
        """
        return ('127.0.0.2', random.randint(1024, (1<<16)-1)) # TODO Change host and port generator 
