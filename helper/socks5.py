# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     socks5
   Description :   pproxy backed socks5 server
   Author :        JHao
   date：          2026/5/17
-------------------------------------------------
   Change Activity:
                   2026/5/17: pproxy socks5 entrypoint
-------------------------------------------------
"""
__author__ = 'JHao'

import atexit
import asyncio
import threading

from handler.configHandler import ConfigHandler
from handler.logHandler import LogHandler
from handler.proxyHandler import ProxyHandler


class Socks5Server(object):
    """Manage a pproxy server backed by the current proxy pool."""

    def __init__(self):
        self.conf = ConfigHandler()
        self.log = LogHandler('socks5_server')
        self.proxy_handler = ProxyHandler()
        self.pproxy = None
        self.loop = None
        self.handler = None
        self.rserver = []
        self.remote_uris = tuple()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self, block=False):
        if not self.conf.socks5Enable:
            self.log.info("Socks5 server disabled")
            return
        try:
            import pproxy
        except ImportError:
            self.log.error("pproxy is not installed, socks5 server skipped")
            return
        self.pproxy = pproxy

        atexit.register(self.stop)
        if block:
            self.__runLoop()
            return

        self.thread = threading.Thread(target=self.__runLoop, name="socks5_server")
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def __runLoop(self):
        self.log.info("Socks5 server manager started")
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self.__refreshLoop())
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self.__stopServer())
            for task in asyncio.all_tasks(self.loop):
                task.cancel()
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()
            self.loop = None

    async def __refreshLoop(self):
        while not self.stop_event.is_set():
            try:
                await self.__refresh()
            except Exception as e:
                self.log.error("Socks5 server refresh error: %s" % e, exc_info=True)
            await asyncio.sleep(self.conf.socks5RefreshSeconds)
        self.loop.stop()

    async def __refresh(self):
        remote_uris = self.__getRemoteUris()
        if not remote_uris:
            if self.handler:
                self.log.info("No upstream proxies, stop socks5 server")
                await self.__stopServer()
            self.rserver[:] = []
            self.remote_uris = tuple()
            return

        if remote_uris != self.remote_uris:
            self.rserver[:] = [self.pproxy.Connection(_) for _ in remote_uris]
            self.remote_uris = remote_uris
            self.log.info("Loaded %s upstream proxies for socks5 server" % len(remote_uris))

        if self.handler:
            return

        await self.__startServer()

    def __getRemoteUris(self):
        proxies = self.proxy_handler.getAll(https=self.conf.socks5HttpsOnly)
        remote_uris = sorted(set([self.__formatHttpRemote(_.proxy) for _ in proxies if _.proxy]))
        return tuple(remote_uris)

    async def __startServer(self):
        listen = "socks5://%s:%s" % (self.conf.socks5Host, self.conf.socks5Port)
        server = self.pproxy.Server(listen)
        args = {
            "rserver": self.rserver,
            "salgorithm": self.conf.socks5Schedule,
            "verbose": self.__verbose,
            "debug": 0,
            "block": None,
            "ruport": False,
        }
        self.handler = await server.start_server(args)
        self.log.info("Start socks5 server on %s with %s upstream proxies" % (listen, len(self.rserver)))

    async def __stopServer(self):
        if not self.handler:
            return

        handler = self.handler
        self.handler = None
        handler.close()
        if hasattr(handler, "wait_closed"):
            await handler.wait_closed()

    def __verbose(self, message):
        self.log.info(message)

    @staticmethod
    def __formatHttpRemote(proxy):
        if "@" not in proxy:
            return "http://%s" % proxy

        auth, address = proxy.rsplit("@", 1)
        return "http://%s#%s" % (address, auth)


def runSocks5(block=False):
    server = Socks5Server()
    server.start(block=block)
    return server
