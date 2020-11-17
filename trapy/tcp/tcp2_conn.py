from trapy.tcp.tcp_pkg import TCPPackage
from trapy.tcp.tcp_log import log
from trapy.tcp.tcp2_exc import ConnException
import trapy.tcp.tcp2_exc as exc
from concurrent.futures import ThreadPoolExecutor, Future
import trapy.utils as ut
from trapy.timer import Timer
import time

class Sender:
    
    DEFAULT_TIMEOUT = 1 # Recommended RFC 6298
    DEFAULT_WINDOW_SIZE = 10
    DEFAULT_PKG_SIZE = 1 # Must be <= MAX_PKG_SIZE
    MAX_PKG_SIZE = 1460
    RTT_WEIGHT = 0.125 # Recommended
    DEV_ERRT_WEIGHT = 0.25 # Recommended
    
    def __init__(self, conn:"Conn", **kwargs):
        self.__executor = ThreadPoolExecutor(1, thread_name_prefix=conn._info())
        self.sock = ut.get_raw_socket()
        self.__conn = conn
        self.ertt = None
        self.dev_ertt = None
        self.pkg_size = self.DEFAULT_PKG_SIZE
        self.window_size = self.DEFAULT_WINDOW_SIZE
        self.timeout = self.DEFAULT_TIMEOUT
        self.timer = Timer(self.timeout)
        self.fast_retr = dict() # ack -> times recv
        self.ack_sent = dict() # expected ack for pkg sent -> (time,count)
        self.finished = True
        self.to_send_queue = [] # data to send may be TCPPackage or bytes
        self.__running = False
        self.sender_task = None
    
    @property
    def timeout_duration(self):
        if self.ertt != None and self.dev_ertt != None:
            return self.ertt + 4 * self.dev_ertt # Recommended
        else:
            return self.DEFAULT_TIMEOUT
    
    def send(self, data:bytes, seq_number:int)->Future:
        """
        Send in a reliable way the `data` starting at `seq_number`  
        return the sending task
        """
        self.base = 0
        self.base_seq_number = seq_number
        self.next_to_send = 0
        self.timer = Timer(self.timeout)
        self.fast_retr = dict() # ack -> times recv
        self.ack_sent = dict() # expected ack for pkg sent -> (time,count)       
        self.finished = False
        self.__running = True
        self.data = data
        self.pkg_sending = None
        self.sender_task = self.__executor.submit(self.__send)
        return self.sender_task
    
    def __send(self):
        while self.__running and self.base < len(self.data):
            window_end = min(self.base + self.window_size * self.pkg_size, len(self.data))
            while self.next_to_send < window_end:
                pkg_sent = self._build_and_send_pkg(self.next_to_send)
                self.next_to_send += len(pkg_sent.data)
            
            if not self.timer.running():
                self.timer.start()

            while self.timer.running() and not self.timer.timeout():
                time.sleep(0.05)
            
            if self.timer.timeout():
                self.next_to_send = self.base
                self.timer.stop()
                self.timer.set_duration(self.timer._duration * 2) # Timeout double the interval
                log.info(f"TIMEOUT {pkg_sent._endpoint_info()} {self.timer._duration}")
            # else:
            #     self.window_size = min(self.window_size, (len(data) - self.base)) # <- Verify if used
        self._reset_variables()
        self._next_scheduled()

    def send_pkg(self, pkg:TCPPackage, reliable=True)->Future:
        """
        Send in a `reliable` way the `pkg`
        return the sending task if `reliable`
        """
        if reliable:
            self.base = 0
            self.next_to_send = len(pkg.data) if pkg.data else 1 
            self.base_seq_number = pkg.seq_number
            self.data = pkg.data
            self.fast_retr = dict() # ack -> times recv
            self.ack_sent = dict() # expected ack for pkg sent -> (time,count)   
            self.pkg_sending = pkg
            self.finished = False
            self.__running = True       
            self.sender_task = self.__executor.submit(self.__send_pkg, pkg)
            return self.sender_task
        else:
            self.__send_pkg_raw(pkg)
    
    def __send_pkg(self, pkg:TCPPackage):
        while self.__running and self.base < 1:
            self.__send_pkg_raw(pkg)
            
            if not self.timer.running():
                self.timer.start()

            while self.timer.running() and not self.timer.timeout():
                time.sleep(0.05)
            
            if self.timer.timeout():
                self.timer.stop()
                self.timer.set_duration(self.timer._duration * 2) # Timeout double the interval
                log.info(f"TIMEOUT {pkg._endpoint_info()} {self.timer._duration}")
        
        self._reset_variables()
        self._next_scheduled()

    def _build_and_send_pkg(self, index:int) -> TCPPackage:
        """
        Build and send a `TCPPackage` indexed in `index`
        """
        if self.data:
            to_send = self.data[index:index+self.pkg_size]
            pkg = TCPPackage.construct_data_pkg(to_send, self.__conn.local_host, 
                                                self.__conn.local_port, self.__conn.dest_host,
                                                self.__conn.dest_port, index + self.base_seq_number, 
                                                self.__conn.ack_number, self.__conn.window_size)
        else:
            pkg = self.pkg_sending
        self.__send_pkg_raw(pkg)
        return pkg

    def _set_expecting_ack(self, expected_ack:int):
        """
        To know when the pkg were sent for first time and how many where sended
        """
        value = self.ack_sent.get(expected_ack,[time.time(), 0])
        value[1] += 1
        self.ack_sent[expected_ack] = value

    def _set_ertt_dev_ertt(self, ack:int):
        value = self.ack_sent.get(ack,None)
        if not value:
            return
        sent_time, sent_times = value
        if sent_times == 1:
            now = time.time()
            rtt = now - sent_time
            if self.ertt:
                self.ertt = (1-self.RTT_WEIGHT) * self.ertt + self.RTT_WEIGHT * rtt
                self.dev_ertt = (1 - self.DEV_ERRT_WEIGHT) * self.dev_ertt + self.DEV_ERRT_WEIGHT * abs(self.ertt - rtt)
            else:
                self.ertt = now - sent_time
                self.dev_ertt = 0
            self.timer.set_duration(self.timeout_duration)
            log.info(f"TIMER RST {self.timeout_duration} {self.__conn._info()}")
            self.ack_sent[ack] = [time,2] # In case of rereceive the ack the time is invalid

    def _next_scheduled(self):
        if self.finished and self.to_send_queue:
            send_next = self.to_send_queue.pop(0)
    
    def _set_sending_rate(self, rcv_window_size:int):
        data_to_send = len(self.data[self.base:])
        byte_window = self.window_size * self.pkg_size
        left_to_send = min(data_to_send, byte_window)
        if left_to_send > rcv_window_size:
            pass # TODO
            

    def __send_pkg_raw(self, pkg:TCPPackage):
        log.info(f"SENT {pkg._info()}")
        self._set_expecting_ack(pkg.expected_ack)
        self.sock.sendto(pkg.to_bytes(), (pkg.dest_host, pkg.dest_port))
        
    def schedule(self, data, reliable = True):
        if reliable:
            if isinstance(data, TCPPackage):
                self.__conn._update_seq(data)
                self.send_pkg(data, True)
            else: # bytes
                seq_number = self.__conn.seq_number
                self.__conn.seq_number += len(data)
                self.send(data, seq_number)
        elif isinstance(data, TCPPackage):
            self.__conn._update_seq(data)
            self.send_pkg(data, False)
        else:
            raise Exception("Only TCPPackages are valid to send in a non reliable way")

    def rcv_pkg(self, ack_pkg:TCPPackage):
        if self.finished:
            return
        
        ack = ack_pkg.ack_number
        rcv_window_size = ack_pkg.window_size
        
        self._set_ertt_dev_ertt(ack)
        self._set_sending_rate(rcv_window_size)
        
        base_seq_num = self.base + self.base_seq_number

        if base_seq_num < ack:
            self.base = ack - self.base_seq_number
            if self.base >= self.next_to_send:
                self.timer.stop()
        else:
            times = self.fast_retr.pop(ack,1)
            if times == 3:
                # Fast Retransmition
                log.info(f"FAST RTM ACK:{ack} {self.__conn._info()}")
                if not self.finished:
                    self._build_and_send_pkg(ack - self.base_seq_number)
            else:
                self.fast_retr[ack] = times + 1

    def close(self, wait=False):
        if wait:
            timer = Timer(10)
            timer.start()
            while not timer.timeout() and not self.finished:
                time.sleep(0.5)
        self.__running = False
        if self.timer:
            self.timer.stop()
        self.__executor.shutdown()
        self.sock.close()

    def _reset_variables(self):
        log.info(f"SENDER STOP {self.__conn._info()}")
        self.finished = True
        self.data = None
        self.pkg_sending = None
        self.fast_retr = dict()
        self.ack_sent = dict()

class Conn:
        
    # Connection States
    SYN_SENT = "SYN SENT" # Initial SYN package sent
    SYNACK_SENT = "SYNACK SENT" # SYN package received and SYNACK package sent 
    FIN_SENT = "FIN SENT" # FIN package sent
    FINACK_SENT = "FINACK SENT" # FIN package received and FINACK package sent
    FIN_WAIT = "FIN WAIT" # FINACK package received and acked, waiting in case of ACK package lost and retransmission of FINACK package occurs
    CONNECTED = "CONNECTED" # Endpoint connected
    LISTEN = "LISTEN" # Server listening for connections
    ACCEPT = "ACCEPT" # Server accepting connections
    CLOSED = "CLOSED" # Endpoint closed
    
    MAX_BUFFER_SIZE = 2048 # Max number of bytes allowed in out buffer
    FIN_WAITING = 5 # Time to wait for connection to close
    
    def __init__(self, local_host:str, local_port:int, dest_host:str, dest_port:int, tcp_layer):
        self.__state = Conn.CLOSED
        self.__close_pkg_sent = True
        self.seq_number = 0
        self.ack_number = 0
        self.dump_buffer = None
        self.dump_number = 0 # seq_number of the first byte in dump_buffer
        self.local_host = local_host
        self.local_port = local_port
        self.dest_host = dest_host
        self.dest_port = dest_port
        self.sender = Sender(self)
        self.__fin_executor = None
        self.__tcp = tcp_layer

    def init_server(self):
        if self.is_server:
            self.state = Conn.LISTEN
            self.accepted_conns = []
            self.accept_count = 0
    
    def init_connection(self):
        syn_pkg = self._build_pkg(b"",ut.PacketFlags(False, False, True, False, False, False, False, False))
        self.state = Conn.SYN_SENT
        self.sender.schedule(syn_pkg)
    
    @property
    def is_server(self) -> bool:
        return self.dest_host == None or self.dest_port == None
    
    @property
    def window_size(self):
        buffer_len = len(self.dump_buffer) if self.dump_buffer else 0
        return self.MAX_BUFFER_SIZE - buffer_len
    
    @property
    def is_closed(self) -> bool:
        return self.state == Conn.CLOSED and self.sender.finished
    
    @property
    def state(self) -> str:
        return self.__state
    
    @state.setter
    def state(self, value:str):
        log.info(f"CHNG CON STATE {self.state}->{value} {self._info()}")
        if value == Conn.CLOSED and self.state != Conn.CLOSED:
            self.__close_pkg_sent = False # Flag for last conn empty pkg
        self.__state = value
    
    def server_handle_pkg(self, pkg:TCPPackage) -> 'Conn':
        if self.state == Conn.ACCEPT and pkg.syn_flag:
            conn = Conn(self.local_host, self.local_port, pkg.source_host, pkg.source_port, self.__tcp)
            self.accepted_conns.append(conn)
            conn.handle_pkg(pkg)
            return conn
            
    def handle_pkg(self, pkg:TCPPackage):
        if pkg.no_flag:
            self._handle_no_flag(pkg)
        else:
            self._update_ack(pkg)
            if pkg.rst_flag:
                self._handle_rst(pkg)
            if pkg.ack_flag:
                self._handle_ack(pkg)
            if pkg.syn_flag:
                self._handle_syn(pkg)
            if pkg.fin_flag:
                self._handle_fin(pkg)
    
    def dump(self, length:int):
        if self.dump_buffer == None:
            if self.state == Conn.CLOSED:
                if self.__close_pkg_sent:
                    raise ConnException(exc.CON_CLOSE_READ_MSG)
                self.__close_pkg_sent = True
                return b""
            return None
        data, self.dump_buffer = self.dump_buffer[:length], self.dump_buffer[length:]
        self.dump_number += len(data)
        if not self.dump_buffer:
            self.dump_buffer = None
            self.dump_number = None
        return data
    
    def send(self, data:bytes)->int:
        init_len = len(data)
        if not len(data):
            flags = ut.PacketFlags(False, False, False, False, False, False, False, False)
            data = self._build_pkg(b"", flags)
        self.sender.schedule(data)
        while not self.sender.finished:
            time.sleep(0.05)
        return init_len
    
    def get_accepted_conn(self):
        if self.state == Conn.LISTEN or self.state == Conn.ACCEPT:
            if self.accepted_conns:
                return self.accepted_conns.pop(0)
    
    def close(self):
        if self.state == Conn.CLOSED:
            raise ConnException(exc.CON_ALREADY_CLOSED_MSG)
        if self.is_server:
            self._close_connection(0)
            return
        flags = ut.PacketFlags(False, False, False, True, False, False, False, False)
        fin_pkg = self._build_pkg(b"", flags)
        self.state = Conn.FIN_SENT
        self.sender.schedule(fin_pkg)
        
    def _handle_syn(self, pkg:TCPPackage):
        if pkg.ack_flag: # SYNACK
            self._send_ack()
            if self.state == self.SYN_SENT:
                self.state = Conn.CONNECTED
        elif self.state == Conn.CLOSED: # SYN
            synack_pkg = self._build_pkg(b"",ut.PacketFlags(True, False, True, False, False, False, False, False))
            self.sender.schedule(synack_pkg)
            self.state = Conn.SYNACK_SENT
            self.__synack_seq_number = synack_pkg.seq_number
            
    def _handle_ack(self, pkg:TCPPackage):
        self.sender.rcv_pkg(pkg)
        if self.state == Conn.SYNACK_SENT and self.__synack_seq_number < pkg.ack_number:
            self.state = Conn.CONNECTED
        if self.state == Conn.FINACK_SENT and self.__finack_seq_number < pkg.ack_number:
            self.state = Conn.CLOSED
            self._close_connection(0)
    
    def _handle_rst(self, pkg:TCPPackage):
        self._close_connection(0)
    
    def _handle_fin(self, pkg:TCPPackage):
        if pkg.ack_flag: # FINACK Pkg
            if self.state == Conn.FIN_SENT:
                self.state = Conn.FIN_WAIT
                # Start waiting
                if not self.__fin_executor:
                    self.__fin_executor = ThreadPoolExecutor(1)
                self.__fin_executor.submit(self._close_connection, self.FIN_WAITING)
            if self.state in [Conn.FIN_WAIT, Conn.FINACK_SENT]: # FINACK_SENT because both endpoints closed at the same time
                self._send_ack()
        elif self.state in [Conn.CONNECTED, Conn.FIN_SENT]: # FIN pkg
            if self.state == Conn.FIN_SENT: # Both endpoints closed at the same time
                pkg = pkg.copy()
                pkg.ack_number += 1 # ACK the FIN PKG
                self.sender.rcv_pkg(pkg)
                while not self.sender.finished:
                    time.sleep(0.05)
            self.state = Conn.FINACK_SENT
            flags = ut.PacketFlags(True, False, False, True, False, False, False, False)
            finack_pkg = self._build_pkg(b"", flags)
            self.__finack_seq_number = finack_pkg.seq_number
            self.sender.schedule(finack_pkg)
    
    def _handle_no_flag(self, pkg:TCPPackage):
        self._update_buffer(pkg)
        self._update_ack(pkg)
        self._send_ack()
    
    def _update_buffer(self, pkg:TCPPackage):
        """
        Update `dump_buffer` with incoming package
        """
        if self.dump_buffer == None: # Buffer not initialized
            if pkg.seq_number == self.ack_number: # Is the pkg expected
                self.dump_buffer = pkg.data
                self.dump_number = pkg.seq_number
        elif self.dump_number <= pkg.seq_number <= self.dump_number + len(self.dump_buffer) < pkg.seq_number + len(pkg.data): # The pkg data has data to get into the dump_buffer
            self.dump_buffer += pkg.data[self.dump_number + len(self.dump_buffer) - pkg.seq_number:]
            
    def _send_ack(self):
        flags = ut.PacketFlags(True, False, False, False, False, False, False, False)
        pkg = self._build_pkg(b"", flags)
        self.sender.schedule(pkg, False)
        return pkg
    
    def _update_ack(self, pkg:TCPPackage):
        """
        Update the ack given a package
        """
            
        if self.ack_number <= pkg.seq_number:
            self.ack_number = ut.next_number(self.ack_number, pkg.seq_number + len(pkg.data) - self.ack_number)
            if not pkg.data and not pkg.only_ack: # Ack the connection management packages
                self.ack_number = ut.next_number(self.ack_number)                 
            return True
        return False
    
    def _update_seq(self, pkg:TCPPackage):
        if pkg.data:
            self.seq_number = max(self.seq_number, pkg.seq_number + len(data))
        elif not pkg.only_ack: # Only pure ack pkg dont raise seq_number, this allow to ack connection management packages
            self.seq_number = max(self.seq_number, pkg.seq_number + 1)
    
    def _build_pkg(self, data:bytes, flags:ut.PacketFlags):
        info = ut.PacketInfo(self.local_host, self.dest_host, self.local_port, self.dest_port,
                             self.seq_number, self.ack_number, 0, flags, 0, self.window_size)
        pkg = TCPPackage(data, info, True)
        return pkg
    
    def _accepting(self, enter:bool):
        """
        Add an accept state
        """
        if enter:
            self.accept_count += 1
        else:
            self.accept_count -= 1
        if self.state in [self.ACCEPT, self.LISTEN]:
            self.state = self.ACCEPT if self.accept_count > 0 else self.LISTEN
    
    def _close_connection(self, timeout:int):
        time.sleep(timeout)
        self.sender.close()
        self.state = Conn.CLOSED
        self.__tcp.remove_connection(self)
        if self.__fin_executor:
            self.__fin_executor.shutdown(False)
        
    def _info(self) -> str:
        if self.is_server:
            return f"{self.local_host}:{self.local_port}"
        else:
            return f"{self.local_host}:{self.local_port}->{self.dest_host}:{self.dest_port}"
            