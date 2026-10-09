"""Standalone Redis TCP server on localhost:6379 using fakeredis.TcpFakeServer."""

import sys
import fakeredis

if __name__ == "__main__":
    print("Starting Redis TCP server on 127.0.0.1:6379...", flush=True)
    server = fakeredis.TcpFakeServer(("127.0.0.1", 6379))
    print("Redis TCP server is ready and listening on port 6379.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        print("Redis server shut down.", flush=True)
