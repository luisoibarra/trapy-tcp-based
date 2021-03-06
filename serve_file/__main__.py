#! /usr/bin/env python

import logging
from concurrent.futures import ThreadPoolExecutor
import sys
sys.path.append(sys.path[0] + "/..")
from trapy.trapy import listen, accept, dial, recv, send, close
from trapy.tcp.tcp import TCP
import time

# uncomment to use working implementation as example
# from trapy.socket_trapy import listen, accept, dial, recv, send, close

logging.basicConfig(format='%(asctime)-15s %(levelname)s %(message)s')
logger = logging.getLogger('serve-file')

logger.setLevel('DEBUG')


def chunked_file(file_path, chunk_size):
    with open(file_path, 'rb') as fp:
        while True:
            data = fp.read(chunk_size)

            if len(data) == 0:
                break

            yield data


def handle(conn, file_path, chunk_size):
    for chunk in chunked_file(file_path, chunk_size):
        send(conn, chunk)
    close(conn)


def make_server(address, file_path, chunk_size):
    logger.info('server running')

    tcp = TCP()
    tcp.start()
    
    executor = ThreadPoolExecutor()
    connections = []

    server = listen(address)

    while True:
        try:
            conn = accept(server)
            future = executor.submit(handle, conn, file_path, chunk_size)

            connections.append((conn, future))
        except KeyboardInterrupt:
            logger.info('closing server')
            break
        except Exception as e:
            logger.exception(e)

    logger.info('releasing resources')
    executor.shutdown(True)


def make_client(address, file_path, chunk_size):
    logger.info('client running')

    tcp = TCP()
    tcp.start()

    conn = dial(address)

    logger.info('client connected to server')

    data = []
    while True:
        chunk = recv(conn, chunk_size)

        if len(chunk) == 0:
            break

        logger.info(f'chunk received. length: {len(chunk)}')

        data.append(chunk)

    data = b''.join(data)

    with open(file_path, 'wb') as fp:
        fp.write(data)

        logger.info(f'data saved. length: {len(data)}')


def main():
    args = make_argumentparser().parse_args()

    if args.dial:
        make_client(args.dial, args.file, args.chunk_size)
    elif args.accept:
        make_server(args.accept, args.file, args.chunk_size)
    else:
        logger.error('you must specify one of dial or accept')


def make_argumentparser():
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--dial',
        help='address to connect to (for client)',
    )
    parser.add_argument(
        '--accept',
        help='address to listen to (for server)',
    )
    parser.add_argument(
        '--file',
        required=True,
        help='path of the file to send (for server) or to store (for client)',
    )
    parser.add_argument(
        '--chunk-size',
        default=1024,
        help='file chunks sizes (for server)',
        type=int
    )

    return parser


if __name__ == '__main__':
    main()
    # executor = ThreadPoolExecutor()
    # address = "127.0.0.2:6500"
    # filename = 'small.txt' 
    # server_file = f'mytests/data/{filename}'
    # client_file = f'mytests/data/tmp-data/{filename}'
    # server = executor.submit(make_server, address, server_file, 1024) 
    # client = executor.submit(make_client, address, client_file)
    # while server.running() or client.running():
    #     time.sleep(0.5)