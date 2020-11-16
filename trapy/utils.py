import struct
import socket as s
from collections import namedtuple

def calculate_checksum(data:bytes):
    """
    Calculates the `data` checksum
    """
    checksum = 0
    info = data
    for i in range(0,len(info),2):
        chunk = info[i:(i+2)]
        if len(chunk) == 1:
            chunk += b'\x00'
        checksum = checksum ^ get_int_of(chunk)
    return checksum

def valid_checksum(data:bytes, checksum:int):
    """
    Returns if a `data` and its `checksum` match
    """
    calculated_checksum = calculate_checksum(data)
    return not calculated_checksum ^ checksum

def parse_address(address:str)->(str,int):
    host, port = address.split(':')

    if host == '':
        host = 'localhost'

    return host, int(port)

def get_byte_of(value, byte_number=1) -> bytes:
    if byte_number == 1:
        return struct.pack('!B',value)
    if byte_number == 2:
        return struct.pack('!H', value)
    if byte_number == 4:
        return struct.pack('!I', value)
    if byte_number == 8:
        return struct.pack('!L', value)

def get_int_of(value) -> int:
    byte_number = len(value)
    if byte_number == 1:
        return struct.unpack('!B',value)[0]
    if byte_number == 2:
        return struct.unpack('!H', value)[0]
    if byte_number == 4:
        return struct.unpack('!I', value)[0]
    if byte_number == 8:
        return struct.unpack('!L', value)[0]

def get_raw_socket() -> s.socket:
    sock = s.socket(s.AF_INET, s.SOCK_RAW, s.IPPROTO_TCP) # AF_INET => IP socket;
    sock.setsockopt(s.IPPROTO_IP, s.IP_HDRINCL, 1) # man 7 raw
    return sock

def get_recv_socket(host:str) -> s.socket:
    sock = get_raw_socket()
    sock.bind((host,1)) # The port has no importance
    return sock

def get_local_hostname():
    return s.gethostbyname(s.gethostname())

def next_number(x:int, n:int=1):
    """
    returns x + n in 32 bits representation
    """
    return (x + n) % (1<<32)

# NAMED TUPLES
PacketFlags = namedtuple('PacketFlags',['ack','rst','syn','fin','ece','cwr','psh','urg'])
PacketInfo = namedtuple('PacketInfo',['source_host', 'dest_host', 'source_port', 'dest_port', 
                                      'seq_number', 'ack_number', 'checksum', 'flags', 'urg_ptr',
                                      'window_size'])

def construct_ip_headers(source_host:str, dest_host:str) -> bytes:
    source_host = b''.join([get_byte_of(int(x)) for x in source_host.split('.')])
    dest_host = b''.join([get_byte_of(int(x))  for x in dest_host.split('.')])
    
    ip_header  = b'\x45\x00\x00\x28'  # Version 4 bit, IHL 4 bit, Type of Service | Total Length
    ip_header += b'\xab\xcd\x00\x00'  # Identification | Flags, Fragment Offset
    ip_header += b'\x40\x06\xa6\xec'  # TTL, Protocol  | Header Checksum  TCP protocol number is 0x06
    ip_header += source_host          # b'\x0a\x00\x00\x01'  # Source Address
    ip_header += dest_host            # b'\x0a\x00\x00\x02'  # Destination Address
    return ip_header

def deconstruct_ip_headers(data:bytes):
    """
    return data_without_ip_headers, (source_host, dest_host) 
    """
    source_host = data[12:16]
    dest_host = data[16:20]
    return data[20:], (".".join([str(int(x)) for x in source_host]), ".".join([str(int(x)) for x in dest_host])) 

def construct_tcp_headers(source_port:int, dest_port:int, sequence_number:int, ack_number:int, 
                          checksum:int, flags:PacketFlags, urg_ptr:int, window_size:int):
    header_length = 5
    header_length__unused_byte = get_byte_of(header_length << 4)

    flag_field = 0
    flag_field |= flags.cwr << 7 | flags.ece << 6 | flags.urg << 5 | flags.ack << 4
    flag_field |= flags.psh << 3 | flags.rst << 2 | flags.syn << 1 | flags.fin << 0
    flag_field = get_byte_of(flag_field)
    
    tcp_header  = b''.join([get_byte_of(x,2) for x in [source_port, dest_port]]) # Source Port | Destination Port
    tcp_header += get_byte_of(sequence_number,4) # Sequence Number
    tcp_header += get_byte_of(ack_number,4) # Acknowledgement Number
    tcp_header += header_length__unused_byte + flag_field + get_byte_of(window_size,2) # Data Offset, Reserved, Flags | Window Size
    tcp_header += get_byte_of(checksum,2) + get_byte_of(urg_ptr,2) # Checksum | Urgent Pointer
    return tcp_header

def deconstruct_tcp_headers(data):
    """
    flags = ack,rst,syn,fin  
    return data_without_tcp_headers, (source_port, dest_port, seq_number, ack_number, checksum, flags, urg_ptr, window_size) 
    """
    source_port = get_int_of(data[:2])
    dest_port = get_int_of(data[2:4])
    sequence_number = get_int_of(data[4:8])
    ack_number = get_int_of(data[8:12])
    header_length = get_int_of(data[12:13])
    flags = get_int_of(data[13:14])
    cwr,ece,urg,ack = 1<<7 & flags != 0, 1<<6 & flags != 0, 1<<5 & flags != 0, 1<<4 & flags != 0
    psh,rst,syn,fin = 1<<3 & flags != 0, 1<<2 & flags != 0, 1<<1 & flags != 0, 1<<0 & flags != 0 
    window_size = get_int_of(data[14:16]) 
    checksum = get_int_of(data[16:18])
    urg_ptr = get_int_of(data[18:20])
    return data[20:], (source_port,dest_port,sequence_number,ack_number,checksum,(ack,rst,syn,fin,ece,cwr,psh,urg),urg_ptr,window_size)

def construct_packet(data:bytes, packet_info:PacketInfo) -> bytes:
    ip_header = construct_ip_headers(packet_info.source_host, packet_info.dest_host)
    protocol_header = construct_tcp_headers(*packet_info[2:])
    return ip_header + protocol_header + data

def deconstruct_packet(data):
    """
    return data_without_headers, (source_host, dest_host, source_port, dest_port, seq_number, ack_number, checksum, flags, urg_ptr)
    """
    data, ip_info = deconstruct_ip_headers(data)
    data, tcp_info = deconstruct_tcp_headers(data)
    info = [x for x in ip_info + tcp_info]
    info[7] = PacketFlags(*info[7]) # info[7] = flags
    info = PacketInfo(*info)
    return data, info

def get_unused_port() -> int:
    import socket
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # just in case
    s.bind(('',0))
    port = s.getsockname()[1]
    s.close()
    return port

def demultiplexing_recv(sock:s.socket, port:int, size:int = 1024, timeout:float = 1, attempts = 3) -> (bytes,PacketInfo):
    old_timeout = sock.gettimeout()
    sock.settimeout(timeout)
    for _ in range(attempts):
        try:
            data = sock.recv(size)
            data, info = deconstruct_packet(data)
            if info.dest_port == port:
                return data, info
        except ConnectionError:
            pass
    
# TEST CONSTRUCTION DECONSTRUCTION
data = b"THE DATA"
flags = PacketFlags(True, False, True, False, False, False, True, True)
pack_info = PacketInfo('127.0.1.2', '127.127.127.127', 65000, 65001, 10, 11, 0, flags,30,125) 
packet_0_checksum = construct_packet(data, pack_info)
pack_info = PacketInfo('127.0.1.2', '127.127.127.127', 65000, 65001, 10, 11, calculate_checksum(packet_0_checksum), flags, 30,125) 
packet = construct_packet(data, pack_info)
print(data)
print(pack_info)
new_data, info = deconstruct_packet(packet)
print(new_data)
print("Checksum valid:", valid_checksum(packet, 0))
print(info)
