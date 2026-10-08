"""获取本机网络信息（主机名、局域网 IP）。"""
from __future__ import annotations

import socket
from typing import List


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def primary_ip() -> str:
    """默认路由出口的本地 IP（即局域网地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ipv4_addresses() -> List[str]:
    """所有非回环 IPv4 地址（含主 IP），排序返回。"""
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(hostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.add(primary_ip())
    return sorted(ip for ip in ips if not ip.startswith("127."))
