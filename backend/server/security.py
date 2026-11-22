"""!
@file security.py
@brief The "only this PC may talk to the backend" guard.

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
    """!
    @brief Answer the question: "may this request be served?".
    """

    def __init__(self, port: int) -> None:
        """!
        @brief Create a guard for one server.
        @param port The port the server listens on; the Origin header must name it.
        """
        self._port = port

    def is_client_allowed(self, client_ip: str) -> bool:
        """!
        @brief Check the address of the TCP client.
        @param client_ip The client's IP address as text.
        @return True only for loopback addresses such as 127.0.0.1 or ::1.

        "::ffff:127.0.0.1" is an IPv4 address wrapped in IPv6 and is unwrapped first.
        """
        try:
            address = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback

    def is_host_header_allowed(self, host_header: Optional[str]) -> bool:
        """!
        @brief Check the Host header.
        @param host_header The header value, or None if missing.
        @return True if it is localhost, 127.0.0.1 or [::1] (port ignored).
        """
        if not host_header:
            return False
        return _split_host(host_header) in _LOOPBACK_HOSTNAMES

    def is_origin_allowed(self, origin: Optional[str]) -> bool:
        """!
        @brief Check the Origin header.
        @param origin The header value, or None if missing.
        @return True if there is no Origin or it is exactly this server, e.g. http://127.0.0.1:8765.

        No Origin header (normal for direct navigation) is fine.
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
    """!
    @brief Extract the host name from a Host header.
    @param host_header One of 'host', 'host:port' or '[::1]:port'.
    @return The lower-case host name without port and brackets.
    """
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host
