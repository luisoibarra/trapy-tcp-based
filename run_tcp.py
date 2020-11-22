import argparse
from trapy.tcp.tcp import TCP

parser = argparse.ArgumentParser()

parser.add_argument("-listen",
                    required=False,
                    type=str, 
                    default="", 
                    help="Listening host of transport layer")

args = parser.parse_args()

tcp = TCP(args.listen)
tcp.start()
tcp.wait()

