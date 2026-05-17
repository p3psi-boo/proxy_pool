# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxy_pool
   Description :   proxy pool 启动入口
   Author :        JHao
   date：          2020/6/19
-------------------------------------------------
   Change Activity:
                   2020/6/19:
-------------------------------------------------
"""
__author__ = 'JHao'

import click
import os
from helper.launcher import startServer, startScheduler, startSocks5
from setting import BANNER, VERSION

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=VERSION)
def cli():
    """ProxyPool cli工具"""


@cli.command(name="schedule")
def schedule():
    """ 启动调度程序 """
    click.echo(BANNER)
    startScheduler()


@cli.command(name="server")
@click.option("--socks5-host", help="SOCKS5服务监听地址")
@click.option("--socks5-port", type=int, help="SOCKS5服务监听端口")
def server(socks5_host, socks5_port):
    """ 启动api服务和socks5服务 """
    setSocks5Options(socks5_host, socks5_port)
    click.echo(BANNER)
    startServer()


@cli.command(name="socks5")
@click.option("--socks5-host", help="SOCKS5服务监听地址")
@click.option("--socks5-port", type=int, help="SOCKS5服务监听端口")
def socks5(socks5_host, socks5_port):
    """ 启动socks5服务 """
    setSocks5Options(socks5_host, socks5_port)
    click.echo(BANNER)
    startSocks5()


def setSocks5Options(host=None, port=None):
    if host:
        os.environ["SOCKS5_HOST"] = host
    if port:
        os.environ["SOCKS5_PORT"] = str(port)


if __name__ == '__main__':
    cli()
