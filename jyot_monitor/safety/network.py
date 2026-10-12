"""Network safety and SSRF-defended attachment downloader."""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests


class NetworkSecurityError(Exception):
    """Raised when a URL violates SSRF or network safety rules."""
    pass


class SafeFetcher:
    """Safe HTTP/HTTPS fetcher with strict SSRF defenses, timeouts, and payload limits."""

    SUPPORTED_MAGIC_BYTES: Dict[str, bytes] = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
        "image/gif": b"GIF8",
        "application/pdf": b"%PDF-",
        "image/webp": b"RIFF",
    }

    def __init__(
        self,
        allowed_schemes: Optional[List[str]] = None,
        max_size_bytes: int = 10 * 1024 * 1024,  # 10 MB
        timeout_seconds: float = 8.0,
        max_redirects: int = 3,
        temp_dir: Optional[str] = None,
    ):
        self.allowed_schemes = allowed_schemes or ["http", "https"]
        self.max_size_bytes = max_size_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.temp_dir = temp_dir or tempfile.gettempdir()

    def validate_url(self, url: str) -> None:
        """Validate URL against SSRF and protocol manipulation."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in self.allowed_schemes:
            raise NetworkSecurityError(f"Unsupported or disallowed URL scheme: {parsed.scheme}")

        hostname = parsed.hostname
        if not hostname:
            raise NetworkSecurityError("URL lacks a valid hostname")

        # Resolve IP addresses for the hostname
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            raise NetworkSecurityError(f"DNS resolution failure for host '{hostname}': {e}")

        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)

            # Block private, loopback, link-local, multicast, reserved ranges
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise NetworkSecurityError(
                    f"Blocked SSRF destination: host '{hostname}' resolves to forbidden IP '{ip_str}'"
                )

    def detect_file_type(self, data: bytes) -> Optional[str]:
        """Detect file MIME type using file signature (magic bytes)."""
        if len(data) < 4:
            return None

        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            return "image/gif"
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"

        return None

    def fetch(self, url: str) -> Tuple[str, str, int]:
        """Safely fetch a remote resource to a temporary file.

        Returns (saved_local_path, detected_mime_type, total_bytes).
        """
        current_url = url
        redirects = 0

        while redirects <= self.max_redirects:
            self.validate_url(current_url)

            # Perform streaming request with redirect following disabled manually for validation
            with requests.get(
                current_url,
                stream=True,
                timeout=self.timeout_seconds,
                allow_redirects=False,
                headers={"User-Agent": "JyotMonitor/1.0 (+https://jyot.in)"},
            ) as response:

                # Check for redirects
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_location = response.headers.get("Location")
                    if not redirect_location:
                        raise NetworkSecurityError("Redirect received without Location header")
                    current_url = urllib.parse.urljoin(current_url, redirect_location)
                    redirects += 1
                    continue

                if response.status_code != 200:
                    raise NetworkSecurityError(f"HTTP fetch failed with status {response.status_code}")

                # Stream content with size limit
                content_chunks: List[bytes] = []
                total_bytes = 0

                for chunk in response.iter_content(chunk_size=8192):
                    total_bytes += len(chunk)
                    if total_bytes > self.max_size_bytes:
                        raise NetworkSecurityError(
                            f"Response size exceeded maximum allowed limit ({self.max_size_bytes} bytes)"
                        )
                    content_chunks.append(chunk)

                full_data = b"".join(content_chunks)
                mime_type = self.detect_file_type(full_data)
                if not mime_type:
                    raise NetworkSecurityError("Fetched file has unsupported or invalid magic bytes")

                # Save safely to temporary file
                ext = ".pdf" if mime_type == "application/pdf" else ".img"
                temp_file = tempfile.NamedTemporaryFile(
                    dir=self.temp_dir, prefix="jyot_fetch_", suffix=ext, delete=False
                )
                temp_file.write(full_data)
                temp_file.close()

                return temp_file.name, mime_type, total_bytes

        raise NetworkSecurityError(f"Exceeded maximum redirect limit of {self.max_redirects}")
