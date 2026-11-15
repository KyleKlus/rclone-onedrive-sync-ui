"""
The "only this PC may talk to the backend" guard.

Three independent checks protect the API:

1. Client address  - the TCP connection must come from a loopback address.
2. Host header     - must name localhost. Stops "DNS rebinding" attacks, where
                     a malicious website tricks the browser into talking to
                     127.0.0.1 under a different name.
3. Origin header   - if a browser sends one, it must be our own page. Stops
                     other websites (or other local web apps on a different
                     port) from sending commands in the background.
"""

import ipaddress
from typing import Optional
from urllib.parse import urlparse

_LOOPBACK_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


class LocalhostGuard:
    """Answers the question: "may this request be served?"."""

    def __init__(self, port: int) -> None:
        self._port = port

    def is_client_allowed(self, client_ip: str) -> bool:
        """True only for loopback addresses such as 127.0.0.1 or ::1."""
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        # "::ffff:127.0.0.1" is an IPv4 address wrapped in IPv6.
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback

    def is_host_header_allowed(self, host_header: Optional[str]) -> bool:
        """The Host header must be localhost, 127.0.0.1 or [::1] (port ignored)."""
        if not host_header:
            return False
        return _split_host(host_header) in _LOOPBACK_HOSTNAMES

    def is_origin_allowed(self, origin: Optional[str]) -> bool:
        """
        No Origin header (normal for direct navigation) is fine. If one is
        present it must be exactly this server, e.g. http://127.0.0.1:8765.
        """
        if not origin:
            return True
        try:
            parsed = urlparse(origin)
            hostname, port = parsed.hostname, parsed.port
        except ValueError:
            return False
        return hostname in _LOOPBACK_HOSTNAMES and port == self._port


def _split_host(host_header: str) -> str:
    """Extract the host name from 'host', 'host:port' or '[::1]:port'."""
    host = host_header.strip().lower()
    if host.startswith("["):                      # IPv6 literal
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host
