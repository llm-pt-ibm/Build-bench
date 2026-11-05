"""The address of the model's API (API_BASE_URL of .env): OpenRouter, or a
server of one's own."""
from typing import Optional


def is_local_url(url: Optional[str]) -> bool:
    """A model server on this machine or the local network."""
    import ipaddress
    from urllib.parse import urlparse
    host = (urlparse(url or "").hostname or "").lower()
    if host in ("localhost",) or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or address.is_private
    except ValueError:
        return False


def api_base(url: Optional[str]) -> Optional[str]:
    """scheme://host[:port] of the model API, without path or credentials."""
    from urllib.parse import urlparse
    if not url:
        return None
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")
