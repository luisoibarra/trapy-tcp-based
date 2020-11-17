import trapy.utils as ut

class TCPPackage:
    
    def __init__(self, data:bytes, info:ut.PacketInfo=None, checksum=False):
        if not info:
            data, info = ut.deconstruct_packet(data)
        self.dest_host = info.dest_host
        self.dest_port = info.dest_port
        self.source_host = info.source_host
        self.source_port = info.source_port
        self.seq_number = info.seq_number
        self.ack_number = info.ack_number
        self.ack_flag = info.flags.ack
        self.syn_flag = info.flags.syn
        self.fin_flag = info.flags.fin
        self.rst_flag = info.flags.rst
        self.ece_flag = info.flags.ece
        self.cwr_flag = info.flags.cwr
        self.psh_flag = info.flags.psh
        self.urg_flag = info.flags.urg
        self.urg_ptr = info.urg_ptr
        self.window_size = info.window_size
        self.data = data
        # Checksum must be last
        self.checksum = info.checksum 
        if checksum: self.update_checksum()
    
    def _calculate_pkg_checksum(self):
        last_checksum = self.checksum
        self.checksum = 0
        pkg_bytes = self.to_bytes()
        checksum = ut.calculate_checksum(pkg_bytes)
        self.checksum = last_checksum
        return checksum

    @property
    def corrupted(self):
        pkg_bytes = self.to_bytes()
        return not ut.valid_checksum(pkg_bytes, 0)

    @property
    def no_flag(self)->bool:
        return not self.fin_flag and not self.ack_flag and not self.rst_flag and not self.syn_flag
    
    @property
    def expected_ack(self)->int:
        if not self.data:
            return self.seq_number + 1
        else:
            return self.seq_number + len(self.data)
    
    @property
    def only_ack(self) -> int:
        return self.ack_flag and not self.syn_flag and not self.fin_flag and not self.rst_flag and\
               not self.ece_flag and not self.urg_flag and not self.psh_flag and not self.cwr_flag
    
    def update_checksum(self):
        self.checksum = self._calculate_pkg_checksum()
    
    def to_bytes(self):
        packet = self._get_packet()
        return ut.construct_packet(self.data, packet)

    def copy(self) -> 'TCPPackage':
        packet = self.to_bytes()
        return TCPPackage(packet)

    def swap_endpoints(self):
        self.source_port, self.source_host, self.dest_port, self.dest_host = self.dest_port, self.dest_host, self.source_port, self.source_host 

    def _get_packet(self)->ut.PacketInfo:
        flags = ut.PacketFlags(self.ack_flag, self.rst_flag, self.syn_flag, self.fin_flag,
                               self.ece_flag, self.cwr_flag, self.psh_flag, self.urg_flag)
        packet = ut.PacketInfo(self.source_host, self.dest_host, self.source_port,
                        self.dest_port, self.seq_number, self.ack_number, self.checksum,
                        flags, self.urg_ptr, self.window_size)
        return packet

    def _endpoint_info(self):
        address = f"{self.source_host}:{self.source_port}->{self.dest_host}:{self.dest_port}" 
        return address

    def _flags_info(self):
        flags = ut.PacketFlags(self.ack_flag, self.rst_flag, self.syn_flag, self.fin_flag,
                               self.ece_flag, self.cwr_flag, self.psh_flag, self.urg_flag)
        str_flags = ""
        for value,name in zip(flags, flags._fields):
            if value:
                str_flags += name.upper() + " "
        else:
            if str_flags:
                str_flags = str_flags[:len(str_flags)-1] # Remove last space if any
            str_flags = "[" + str_flags + "]"
        return str_flags

    def _info(self):
        address = self._endpoint_info()
        pkg_num = f"SEQ:{self.seq_number} ACK:{self.ack_number}"
        flags = self._flags_info()
        return f"PKG {address} {pkg_num} {flags}"

    @staticmethod
    def construct_data_pkg(data:bytes, local_host:str, local_port:int, dest_host:str, dest_port:int, 
                           seq_number:int, ack_number:int, window_size:int)->'TCPPackage':
        flags = ut.PacketFlags(False, False, False, False, False, False, False, False)
        info = ut.PacketInfo(local_host, dest_host, local_port, dest_port, seq_number, ack_number,
                             0, flags, 0, window_size)
        return TCPPackage(data, info, True)
    