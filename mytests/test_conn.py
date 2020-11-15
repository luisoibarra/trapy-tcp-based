import unittest
from mytests import log, TCP
import time
from trapy.tcp.trapy import send, recv, dial, listen, accept, close
from concurrent.futures import ThreadPoolExecutor

class TestConn(unittest.TestCase):
    def setUp(self):
        self.address = "127.0.0.2:6500"
        self.executor = ThreadPoolExecutor(2)
        self.server, self.server_con, self.client_con = None, None, None
    
    def tearDown(self):
        self.tcp.close_all()
        self.executor.shutdown()
    
    @classmethod
    def setUpClass(cls):
        cls.tcp = TCP()
        cls.tcp.start()
    
    @classmethod
    def tearDownClass(cls):
        cls.tcp.end()
   
    def test_end_conn(self):
        def server_test():
            self.server = listen(self.address)
            self.server_con = accept(self.server)
            close(self.server)
            close(self.server_con)
            
        def client_test():
            self.client_con = dial(self.address)
            close(self.client_con)
            
        server_task = self.executor.submit(server_test)
        client_task = self.executor.submit(client_test)
        time.sleep(0.5)
        while server_task.running() or client_task.running():
            time.sleep(0.5)
        
        self.assertEqual(self.server_con.state, TCP.CLOSED, "Server connection is not closed")
        self.assertEqual(self.client_con.state, TCP.CLOSED, "Client connection is not closed")
        self.assertEqual(len(self.tcp.conn_dict.conn_dict),0, "Client Connections not removed from TCP dictionary")
        self.assertEqual(len(self.tcp.conn_dict.server_conn_dict),0, "Server Connections not removed from TCP dictionary")
    
    def test_init_conn(self):
        def server_test():
            self.server = listen(self.address)
            self.server_con = accept(self.server)
            
        def client_test():
            self.client_con = dial(self.address)
            
        server_task = self.executor.submit(server_test)
        client_task = self.executor.submit(client_test)
        time.sleep(0.5)
        while server_task.running() or client_task.running():
            time.sleep(0.5)
        
        self.assertEqual(self.server_con.state, TCP.CONNECTED, "Server connection is not connected")
        self.assertEqual(self.client_con.state, TCP.CONNECTED, "Client connection is not connected")
    
    def test_data_transfer(self):
        def send_test(pkg_size=10):
            self.server = listen(self.address)
            self.server_con = accept(self.server)
            initial_data = data = b"123456789a123456789b123456789c123456789d123456789e123456789f123456789g"
            size = pkg_size
            while data:
                pkg, data = data[:size], data[size:]
                len_send = send(self.server_con, pkg)
                data = pkg[len_send:] + data
            return initial_data
            
        def rcv_test():
            self.client_con = dial(self.address)
            data = b''
            rcv_data = True
            while rcv_data:
                rcv_data = recv(self.client_con, 1)
                data += rcv_data
            return data
            
        server_task = self.executor.submit(send_test)
        client_task = self.executor.submit(rcv_test)
        time.sleep(0.5)
        while server_task.running() or client_task.running():
            time.sleep(0.5)
        
        self.assertEqual(server_task.result(), client_task.result(), "Data sended and received are different")
        
    def test_both_data_transfer(self):
        def send_test(pkg_sent_size=10,pkg_rcv_size=10):
            self.server = listen(self.address)
            self.server_con = accept(self.server)
            initial_data = data = b"123456789a123456789b123456789c123456789d123456789e123456789f123456789g"
            
            size = pkg_sent_size
            while data:
                pkg, data = data[:size], data[size:]
                len_send = send(self.server_con, pkg)
                data = pkg[len_send:] + data
            send(self.server_con, b"")
            
            data = b''
            rcv_data = True
            while rcv_data:
                rcv_data = recv(self.server_con, pkg_rcv_size)
                data += rcv_data
            return initial_data, data
            
        def rcv_test(pkg_sent_size=10,pkg_rcv_size=10):
            self.client_con = dial(self.address)
            data = b''
            rcv_data = True
            while rcv_data:
                rcv_data = recv(self.client_con, pkg_rcv_size)
                data += rcv_data
            recv_data = data
            
            initial_data = data = b"123456789a123456789b123456789c123456789d123456789e123456789f123456789g"
            size = pkg_sent_size
            while data:
                pkg, data = data[:size], data[size:]
                len_send = send(self.client_con, pkg)
                data = pkg[len_send:] + data
            return initial_data, recv_data
            
        server_task = self.executor.submit(send_test)
        client_task = self.executor.submit(rcv_test)
        time.sleep(0.5)
        while server_task.running() or client_task.running():
            time.sleep(0.5)
            
        sent,rcv = client_task.result()
        value = rcv,sent
        self.assertEqual(server_task.result(), value, "Data sended and received are different")
        
if __name__ == "__main__":
    unittest.main()  

