import socket as s
import trapy.utils as ut
from trapy.timer import Timer
import random
import time
import datetime
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor, Future
from trapy.tcp.tcp_pkg import TCPPackage
import logging as log
log.basicConfig(level=log.DEBUG, format='[%(asctime)s] %(levelname)s - %(message)s')

class Sender:
    
    DEFAULT_TIMEOUT = 1 # Recommended RFC 6298
    DEFAULT_WINDOW_SIZE = 10
    DEFAULT_PKG_SIZE = 1
    RTT_WEIGHT = 0.125 # Recommended
    DEV_ERRT_WEIGHT = 0.25 # Recommended
    
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
        self.to_send_ack_count = [0 for _ in range(len(self.to_send))] # To Provide Fast Retransmit 
        self.base = 0
        self.window_size = kwargs.get('window_size',self.DEFAULT_WINDOW_SIZE)
        self.next_to_send = self.base
        self.ertt = None # Estimated round trip time
        self.dev_ertt = None # Deviation of ertt
        self.base_send_count = [self.base, 0, None] # Count how many times the base pkg was sent, the third element is the sending time of the first pkg if only one was sent
        self.timer = Timer(kwargs.get('timeout',self.DEFAULT_TIMEOUT))
        self.__running = True
        self.finished = False
        self.sender_task = self.executor.submit(self._send)
        return self.sender_task
    
    def _send(self):
        while self.__running and self.base < len(self.to_send):
            window_end = min(self.base+self.window_size, len(self.to_send))
            while self.next_to_send < window_end:
                self._update_base_send_count()
                
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
                self.timer.set_duration(self.timer._duration * 2) # Timeout double the interval
                log.info(f"TIMEOUT {self.to_send[0]._endpoint_info()} {self.timer._duration}")
            else:
                self.window_size = min(self.window_size, len(self.to_send) - self.base)
        self.finished = True

    def ack_package(self, ack:int):
        if self.finished or self.base == len(self.to_send):
            return

        for i, pkg in enumerate(self.to_send[:self.base+self.window_size], self.base):
            pkg_expected_ack = pkg.seq_number + len(pkg.data) if pkg.data else pkg.seq_number + 1
            if pkg_expected_ack == ack and self.base <= i:
                self.base = i + 1
                self._update_ertt()
                if self.base == self.next_to_send: # ACK the last pkg sent
                    self.timer.stop()
                    self.timer.set_duration(self.timeout_duration)
                    log.info(f"TIMEOUT RESET {self.to_send[0]._endpoint_info()} {self.timer._duration}")
                break
            if pkg_expected_ack == ack:
                # Fast Retransmit
                self.to_send_ack_count[i] += 1
                if not self.to_send_ack_count[i] % 3:
                    log.info(f"FAST RETR {pkg._info()}")
                    self.send_sock.sendto(pkg.to_bytes(), (pkg.dest_host, pkg.dest_port))
                                        
    @property
    def timeout_duration(self):
        if self.ertt != None and self.dev_ertt != None:
            return self.ertt + 4 * self.dev_ertt # Recommended
        else:
            return self.DEFAULT_TIMEOUT
     
    def close(self):
        timer = Timer(10)
        timer.start()
        while not timer.timeout() and self.sender_task and self.sender_task.running():
            time.sleep(0.5)
        self.__running = False
        if self.timer:
            self.timer.stop()
        self.executor.shutdown()
        self.send_sock.close()

    def _update_ertt(self):
        """
        If the conditions are satisfied update the `ertt` and `dev_ertt` values 
        """
        if self.base > self.base_send_count[0] and self.base_send_count[2]:
            now = time.time()
            sent_time = self.base_send_count[2]
            rtt = now - sent_time
            if self.ertt:
                self.ertt = (1-self.RTT_WEIGHT) * self.ertt + self.RTT_WEIGHT * rtt
                self.dev_ertt = (1 - self.DEV_ERRT_WEIGHT) * self.dev_ertt + self.DEV_ERRT_WEIGHT * abs(self.ertt - rtt)
            else:
                self.ertt = now - sent_time
                self.dev_ertt = 0
            self.timer.set_duration(self.timeout_duration)
        self.base_send_count = [self.base, 0, None]

    def _update_base_send_count(self):
        if self.base_send_count[0] == self.next_to_send:
            self.base_send_count[1] += 1
            if self.base_send_count[1] == 1:
                self.base_send_count[2] = time.time()
            else:
                self.base_send_count[2] = None
        
class BatchPackageBuilder:
    """
    Build packages for the associated Conn instance  
    Handling flow control <- TODO this can be done by passing extra info when building packages or by putting this info in the conn instance 
    """
    
    def __init__(self, conn:'TCPConn'):
        self.__conn = conn
    
    def build_packages(self, data:bytes, max_pkg_size:int=Sender.DEFAULT_PKG_SIZE, max_amount:int=-1):
        """
        Build a list of packages of sizes <= `max_pkg_size`  
        The length of the list is <= `max_amount` in case of `max_amount` > 0  
        return remaining_data,packages 
        """
        max_amount = max_amount if max_amount > 0 else (1<<32)-1
        packages = []
        empty_pkg = data == b""            
        while empty_pkg or data and len(packages) < max_amount:
            pkg, data = data[:max_pkg_size], data[max_pkg_size:]
            flags = ut.PacketFlags(False, False, False, False, False, False, False, False)
            info = ut.PacketInfo(self.__conn.local_host,self.__conn.dest_host,self.__conn.local_port,
                                self.__conn.dest_port, self.__conn._use_seq_number(len(pkg)),self.__conn.ack_number,0,
                                flags,0,self.window_size)
            package = TCPPackage(pkg, info, checksum=True)
            packages.append(package)
            empty_pkg = False
        
        return packages, data
    
class Conn:
    """
    Base Conn class
    """

    MAX_BUFFER_SIZE = 2048
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        self.local_host = host
        self.local_port = port
        
        self.in_buffer = []
        self.base_seq_number = 0 # random.randint(0,(1<<32)-1) # initial seq number
        self.seq_number = self.base_seq_number # current seq_number
        
        self.recv_executor = ThreadPoolExecutor(max_workers=1)
        self.recv_task = None
        self.sender = Sender()
        self.sender_task = None
        
        self.state = TCP.CLOSED
        
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
            if package.corrupted:
                continue
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
        if self.sender_task and not self.sender.finished:
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
        self.state = TCP.CLOSED
        self.recv_executor.shutdown()
    
    def _send_ack(self):
        """
        Send an ack package of `package`
        """
        flags = ut.PacketFlags(True, False, False, False, False, False, False, False)
        ack_pkg = ut.PacketInfo(self.local_host, self.dest_host, self.local_port, self.dest_port,
                                self.seq_number, self.ack_number, 0, flags, 0, self.window_size if hasattr(self,'window_size') else 0)
        ack_pkg = TCPPackage(b'', ack_pkg, True)
        log.info(f"ACK Sent {ack_pkg._info()}")
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
        
    Initiate Connection:
    3-way handshake
    
    Close Connection:
    3-way handshake
    """
    
    FIN_WAITING = 5 # Time to wait for connection to close
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        super().__init__(host, port, *args, **kwargs)
        self.base_ack_number = None # Initial other side seq_number
        self.ack_number = self.base_ack_number # expected byte from other side
        self.dest_host = None
        self.dest_port = None
        self.sended_fin = None # ut.PackageInfo of FIN package
        self.responded_fin = None # ut.PackageInfo of FINACK package
        self.to_dump = None # byte to dump 
        self.in_package_data = dict() # seq_number -> data
        self.dump_buffer = b''
        self.heavy_sender = Sender()
        self.builder = BatchPackageBuilder(self)
        self.fin_timer = Timer(self.FIN_WAITING)
        self._synack_package = None
        self.__server = kwargs.get('server', None)

    @property
    def window_size(self):
        spare_space = self.MAX_BUFFER_SIZE - (len(self.dump_buffer) + sum([len(data) for key,data in self.in_package_data.items()]))
        if spare_space < 0:
            return 0
        return spare_space
    
    def handle_rst_package(self, package: TCPPackage):
        pass

    def handle_ack_package(self, package:TCPPackage):
        if self.state == TCP.SYNACK_SENT:
            self.establish_connection(package)
        if self.state != TCP.CONNECTED:
            self._update_ack(package)
        super().handle_ack_package(package)
        if self.state == TCP.FINACK_SENT and package.seq_number >= self.responded_fin.ack_number: # if the responded_fin pkg was acked
            self._release_resources()
        elif self.heavy_sender.sender_task and not self.heavy_sender.finished:
            self.heavy_sender.ack_package(package.ack_number)
    
    def handle_no_flag_package(self, package:TCPPackage):
        if self.state == TCP.CONNECTED:
            if self.window_size: # There are space left in buffer
                self._update_buffer(package)
                self._update_ack(package)
                self._send_ack()

    def send(self, data:bytes):
        init_length = len(data)
        if self.heavy_sender.sender_task and not self.heavy_sender.finished:
            raise ConnException("Already sending data")
        empty_pkg = data == b""
        while empty_pkg or data:
            # Send all data <- TODO This is not necessary maybe can send only a piece
            packages, data = self.builder.build_packages(data)
            self.heavy_sender.sender_task = self.heavy_sender.send(packages, packages[0].seq_number)
            while not self.heavy_sender.finished:
                time.sleep(0.1)
            empty_pkg = False
        return init_length
    
    def dump(self, length:int):
        """
        return the received data up to `length` bytes
        """
        if self.dump_buffer and len(self.dump_buffer) >= length:
            data, self.dump_buffer = self.dump_buffer[:length], self.dump_buffer[length:]
            return data
        
        if self.in_package_data:
            next_data = self.in_package_data.pop(self.to_dump,None)
            to_dump = None if next_data == None else b""
            while next_data != None:
                self.to_dump += len(next_data) if next_data else 1
                to_dump += next_data
                next_data = self.in_package_data.pop(self.to_dump,None)
            
            if to_dump == None: # Next package missing
                return None
            
            self.dump_buffer += to_dump
            to_dump, self.dump_buffer = self.dump_buffer[:length], self.dump_buffer[length:]
            log.info(f"DUMP {self._info()} {to_dump}")
            return to_dump
        if self.state == TCP.CLOSED:
            return b""
    
    # Handshake    
    def init_connection(self, address:str):
        """
        Send SYN package to `address`
        """
        host, port = ut.parse_address(address)
        self.dest_host = host
        self.dest_port = port
        flags = ut.PacketFlags(False, False, True, False, False, False, False, False)
        syn_package = TCPPackage(b'',ut.PacketInfo(self.local_host,self.dest_host,self.local_port,
                                                   self.dest_port, self._use_seq_number(), 0, 0, 
                                                   flags, 0, self.window_size),True)
        self.state = TCP.SYN_SENT
        self._send(syn_package)
        
    def handle_syn_package(self, package:TCPPackage):
        if self.state == TCP.SYN_SENT and package.ack_flag and package.ack_number == self.seq_number\
            or self.state == TCP.CONNECTED:
                
            if self.state == TCP.SYN_SENT:
                # Set other endpoint variables
                self.base_ack_number = package.seq_number
                self.ack_number = ut.next_number(package.seq_number)
                self.to_dump = self.ack_number # The first byte to dump is the first expected 
                self.state = TCP.CONNECTED
            self.ack_server_handshake(package)
        
    def ack_server_handshake(self, server_package:TCPPackage):
        """
        Acknowledge the handshake message (`server_package`) from client  
        Prepare the current connection to send-receive process
        """
        if not self._synack_package:
            # Build send package
            response = server_package.copy()
            response.swap_endpoints()
            response.syn_flag = False
            response.seq_number = self._use_seq_number()
            response.ack_number = self.ack_number
            response.update_checksum()
            self._synack_package = response
        
        # Send package
        self._send(self._synack_package, False)

    def establish_connection(self, package:TCPPackage):
        """
        Last step of initial handshake
        """
        if self.ack_number == package.seq_number:
            self.state = TCP.CONNECTED
            self.seq_number = package.ack_number
            self.ack_number = ut.next_number(package.seq_number)
            self.to_dump = self.ack_number
            self.__server._connection_established(self)
            self.__server = None
    ##
    
    # End Connection
    def handle_fin_package(self, package:TCPPackage):
        if self.state == TCP.CONNECTED or self.state == TCP.FINACK_SENT:
            # fin received from other endpoint
            
            self._update_ack(package) # Because ack flag is off the ack_number is not updated
            
            # Send fin ack
            if not self.responded_fin:
                flags = ut.PacketFlags(True, False, False, True, False, False, False, False)
                self.responded_fin = ut.PacketInfo(self.local_host, self.dest_host, self.local_port,
                                            self.dest_port, self._use_seq_number(), self.ack_number, 0, 
                                            flags, 0, self.window_size)
                self.state = TCP.FINACK_SENT
            self._send(TCPPackage(b'', self.responded_fin, True))
            
        elif self.state == TCP.FIN_SENT or self.state == TCP.FIN_WAIT and package.ack_flag:
            # fin received from other endpoint that received this peer fin package 
            # import time
            # time.sleep(15) # Waiting
            if not self.fin_timer.running():
                self.fin_timer.start()
                self.state = TCP.FIN_WAIT
                self._send_ack()
            elif not self.fin_timer.timeout():
                self._send_ack()
    
    def close(self):
        """
        Start the closing process by sending a FIN pkg
        """
        if self.state == TCP.CONNECTED:
            flags = ut.PacketFlags(False, False, False, True, False, False, False, False)
            self.sended_fin = ut.PacketInfo(self.local_host, self.dest_host, self.local_port,
                                        self.dest_port, self._use_seq_number(), self.ack_number, 0, 
                                        flags, 0, self.window_size)
            self.state = TCP.FIN_SENT
            self._send(TCPPackage(b'', self.sended_fin, True))
        else:
            self._release_resources()
    ##
    
    def _info(self) -> str:
        return f"CON {self.local_host}:{self.local_port}->{self.dest_host}:{self.dest_port} SEQ:{self.seq_number} ACK:{self.ack_number}"
    
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
    
    def _update_buffer(self, package:TCPPackage):
        if package.seq_number == self.to_dump:
            self.dump_buffer += package.data
            
            self.in_package_data[package.seq_number] = package.data
    
    def _release_resources(self):
        self.heavy_sender.close()
        super()._release_resources()

class TCPConnServer(Conn):
    """
    Hold the server connection state 
    """
    
    def __init__(self, host:str, port:int, *args, **kwargs):
        super().__init__(host, port, *args, **kwargs)
        self.accepted_connections = []
        self.pending_ack_conn = dict() # host,port -> expected_ack_number, TCPConn
    
    def start(self):
        self.state = TCP.LISTEN
        super().start()
    
    def accept(self):
        if self.state == TCP.LISTEN:
            self.state = TCP.ACCEPT
            while not self.accepted_connections:
                time.sleep(0.5) # TODO Timer?
            
            # Go back to previous state in case of not been changed
            if self.state == TCP.ACCEPT:
                self.state = TCP.LISTEN
                
            return self.accepted_connections.pop()
        else:
            raise ConnException("Server not listening")
    
    def handle_rst_package(self, package:TCPPackage):
        self.pending_ack_conn.pop((package.source_host, package.source_port),None)
    
    def handle_fin_package(sef, package:TCPPackage):
        pass
    
    def handle_no_flag_package(package):
        pass
    
    # Handshake   
    def handle_syn_package(self, package:TCPPackage):
        if self.state == TCP.ACCEPT:
            key = package.source_host, package.source_port
            if not key in self.pending_ack_conn:
                self.response_handshake(package)
            

    def response_handshake(self, initial_package:TCPPackage):
        """
        Sends server synack package of the handshake initiated by `initial_package`
        """
        
        # Create New Connection
        conn = TCPConn(initial_package.dest_host, initial_package.dest_port, server=self)
        conn.dest_host = initial_package.source_host
        conn.dest_port = initial_package.source_port
        conn.ack_number = ut.next_number(initial_package.seq_number)
        conn.base_ack_number = initial_package.ack_number
        conn.state = TCP.SYNACK_SENT
        conn.start()
        
        # Create This Connection
        TCP.add_connection(conn)
        
        # Create package
        send_package = self._build_synack_package(initial_package, conn.seq_number, conn.local_port)
        
        # Save conn to last ack packet
        self.pending_ack_conn[send_package.dest_host,send_package.dest_port] = ut.next_number(send_package.seq_number),conn
        
        # Send package
        conn._send(send_package)
    
    def close(self):
        self._release_resources()
    
    def _build_synack_package(self, syn_package:TCPPackage, conn_seq_number:int, conn_port:int):
        # Create package
        send_package = syn_package.copy()
        send_package.swap_endpoints()
        send_package.ack_flag = True
        send_package.ack_number = ut.next_number(syn_package.seq_number)
        send_package.seq_number = conn_seq_number
        
        send_package.update_checksum()
        return send_package
    
    def _connection_established(self, conn:TCPConn):
        """
        Called from `conn` to finish server dependencies
        """
        key = conn.dest_host, conn.dest_port
        expected_ack, conn = self.pending_ack_conn.pop(key,(None,None))
        if conn:
            self.accepted_connections.append(conn)
    
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
    
    # TCP Connection States
    SYN_SENT = "SYN SENT" # Initial SYN package sent
    SYNACK_SENT = "SYNACK SENT" # SYN package received and SYNACK package sent 
    FIN_SENT = "FIN SENT" # FIN package sent
    FINACK_SENT = "FINACK SENT" # FIN package received and FINACK package sent
    FIN_WAIT = "FIN WAIT" # FINACK package received and acked, waiting in case of ACK package lost and retransmission of FINACK package occurs
    CONNECTED = "CONNECTED" # Endpoint connected
    LISTEN = "LISTEN" # Server listening for connections
    ACCEPT = "ACCEPT" # Server accepting connections
    CLOSED = "CLOSED" # Endpoint closed
    
    # Socket that receive all packages
    recv_sock = ut.get_raw_socket()
    
    # All TCP connections
    conn_dict = ConnectionDict()
    
    def __init__(self, *args, **kwargs):
        # self.recv_sock.bind(('',0)) # Receive all connections 
        self.recv_sock.bind(('127.0.0.2',0)) # TODO Non Production Bind Address
        self.recv_thread = Thread(target=self.demultiplex, name='TCP', daemon=True)
        self.__running = False

    def start(self):
        """
        Start the TCP functionality.  
        Must be called before any other method
        """
        self.__running = True
        self.recv_thread.start()
        log.info("TCP Started")
        
    
    def end(self):
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
            if self._can_queue_data(package):
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
                
    @staticmethod
    def start_server(address:str) -> TCPConnServer:
        """
        return a working TCPConnServer binded to `address`
        """
        host, port = ut.parse_address(address)
        conn = TCPConnServer(host,port)
        TCP.conn_dict.add_server(host, port, conn)
        conn.start()
        return conn
    
    @staticmethod
    def start_connection(address:str) -> TCPConn:
        """
        return a TCPConn connected to address
        """
        conn = TCPConn(*TCP._get_address())
        conn.dest_host, conn.dest_port = ut.parse_address(address)
        conn.start()
        TCP.add_connection(conn)
        conn.init_connection(address)
        while conn.state != TCP.CONNECTED:
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
    def accept(conn:TCPConnServer):
        return conn.accept()
    
    @staticmethod
    def send(conn:TCPConn, data:bytes):
        return conn.send(data)
    
    @staticmethod
    def recv(conn:TCPConn, length:int):
        data = None
        while data == None:
            data = conn.dump(length)
            time.sleep(0.1)
        return data
    
    def _can_queue_data(self, pkg:TCPPackage):
        """
        returns if the `pkg` must be queued
        """
        # if not pkg.syn_flag and pkg.ack_flag and not pkg.data: # Simulate data lost
        #     return False
        # if pkg.no_flag:
        #     return random.choice([True, False]) # Simulate unreliable transport medium
        return True
        # return random.choice([True, False]) # Simulate unreliable transport medium
    
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
    
    def close_all(self):
        keys = [x for x in self.conn_dict.server_conn_dict]
        for key in keys:
            conn = self.conn_dict.server_conn_dict[key]
            conn.close()
        keys = [x for x in self.conn_dict.conn_dict]
        for key in keys:
            conn = self.conn_dict.conn_dict[key]
            conn.close()
    
    @staticmethod
    def _get_address() -> (str,int):
        """
        return the initial address of a new TCPConn
        """
        return ('127.0.0.2', random.randint(1024, (1<<16)-1)) # TODO Change host and port generator 
