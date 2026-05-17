# -*- coding: utf-8 -*-
"""
End-to-end test for the pproxy backed socks5 server.

The test starts a temporary Redis instance, a target HTTP server, and a local
HTTP CONNECT proxy. Then it stores that proxy in ProxyPool and verifies a raw
SOCKS5 client can reach the target through the full chain.
"""
__author__ = 'JHao'

import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import time

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)


def getFreePort():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def waitPort(port, host="127.0.0.1", timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=0.2)
            sock.close()
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("port %s is not ready" % port)


class TargetHandler(socketserver.BaseRequestHandler):
    request_count = 0

    def handle(self):
        TargetHandler.request_count += 1
        self.request.recv(4096)
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\nhello socks"
        )


class ConnectProxyHandler(socketserver.BaseRequestHandler):
    connect_count = 0

    def handle(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk

        request_line = data.split(b"\r\n", 1)[0].decode("ascii")
        method, address, _ = request_line.split(" ", 2)
        if method.upper() != "CONNECT":
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return

        ConnectProxyHandler.connect_count += 1
        host, port = address.rsplit(":", 1)
        upstream = socket.create_connection((host, int(port)), timeout=5)
        self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        try:
            self.__relay(self.request, upstream)
        finally:
            upstream.close()

    @staticmethod
    def __relay(client, upstream):
        client.settimeout(5)
        upstream.settimeout(5)
        request = client.recv(4096)
        upstream.sendall(request)
        while True:
            data = upstream.recv(4096)
            if not data:
                break
            client.sendall(data)


def socks5HttpGet(socks_port, target_port):
    sock = socket.create_connection(("127.0.0.1", socks_port), timeout=5)
    try:
        sock.sendall(b"\x05\x01\x00")
        assert sock.recv(2) == b"\x05\x00"

        host = b"127.0.0.1"
        request = b"\x05\x01\x00\x03" + bytes([len(host)]) + host + target_port.to_bytes(2, "big")
        sock.sendall(request)
        response = sock.recv(10)
        assert response[:2] == b"\x05\x00", response

        sock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        sock.close()


def testSocks5E2E():
    if shutil.which("redis-server") is None:
        raise RuntimeError("redis-server is required for this e2e test")

    redis_port = getFreePort()
    socks_port = getFreePort()
    target_port = getFreePort()
    connect_proxy_port = getFreePort()
    temp_dir = tempfile.mkdtemp(prefix="proxy_pool_e2e_")

    env = {
        "DB_CONN": "redis://@127.0.0.1:%s/15" % redis_port,
        "TABLE_NAME": "test_socks5_e2e",
        "SOCKS5_HOST": "127.0.0.1",
        "SOCKS5_PORT": str(socks_port),
        "SOCKS5_REFRESH_SECONDS": "1",
        "SOCKS5_SCHEDULE": "rr",
        "SOCKS5_HTTPS_ONLY": "true",
    }
    os.environ.update(env)

    redis = subprocess.Popen([
        "redis-server",
        "--port", str(redis_port),
        "--dir", temp_dir,
        "--save", "",
        "--appendonly", "no",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    target_server = socketserver.ThreadingTCPServer(("127.0.0.1", target_port), TargetHandler)
    connect_proxy = socketserver.ThreadingTCPServer(("127.0.0.1", connect_proxy_port), ConnectProxyHandler)

    socks_server = None
    target_server_thread = None
    connect_proxy_thread = None
    try:
        waitPort(redis_port)

        from handler.proxyHandler import ProxyHandler
        from helper.proxy import Proxy
        from helper.socks5 import runSocks5

        proxy_handler = ProxyHandler()
        proxy_handler.put(Proxy("127.0.0.1:%s" % connect_proxy_port, https=True, source="e2e"))

        target_server_thread = __startServerThread(target_server)
        connect_proxy_thread = __startServerThread(connect_proxy)
        socks_server = runSocks5()
        waitPort(socks_port)

        data = socks5HttpGet(socks_port, target_port)
        assert b"200 OK" in data, data
        assert b"hello socks" in data, data
        assert ConnectProxyHandler.connect_count == 1
        assert TargetHandler.request_count == 1

        target_server_thread.join(0)
        connect_proxy_thread.join(0)
        print("Socks5 e2e ok")
    finally:
        if socks_server:
            socks_server.stop()
        if target_server_thread:
            target_server.shutdown()
        target_server.server_close()
        if connect_proxy_thread:
            connect_proxy.shutdown()
        connect_proxy.server_close()
        redis.terminate()
        try:
            redis.wait(timeout=5)
        except subprocess.TimeoutExpired:
            redis.kill()
            redis.wait()
        shutil.rmtree(temp_dir)


def __startServerThread(server):
    import threading

    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return thread


if __name__ == '__main__':
    testSocks5E2E()
