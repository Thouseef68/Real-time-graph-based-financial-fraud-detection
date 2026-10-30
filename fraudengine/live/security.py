"""Security, IP derivation, privacy masking, and gateway allowlisting for Live Demo."""

from __future__ import annotations

import ipaddress
import secrets
from typing import Mapping, Optional, Tuple


def derive_client_ip(peer_ip: str, headers: Mapping[str, str]) -> str:
    """Derive client IP from forwarded headers when direct peer is loopback or trusted private reverse proxy (Render, Cloudflare, etc.).
    
    If direct peer is an external untrusted public IP, forwarded headers are ignored to prevent spoofing.
    """
    clean_peer = (peer_ip or "127.0.0.1").strip().lower()
    
    is_loopback = clean_peer in ("127.0.0.1", "::1", "localhost", "testclient")
    is_trusted = is_loopback

    import os
    if not is_trusted and bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("TRUST_PROXY_HEADERS")):
        try:
            ip_obj = ipaddress.ip_address(clean_peer)
            if ip_obj.is_private:
                is_trusted = True
        except Exception:
            pass

    if is_trusted:
        # Cloudflare tunnel header
        cf_ip = headers.get("cf-connecting-ip")
        if cf_ip and cf_ip.strip():
            return cf_ip.strip().split(",")[0].strip()
        
        # Standard X-Forwarded-For
        xfwd = headers.get("x-forwarded-for")
        if xfwd and xfwd.strip():
            return xfwd.strip().split(",")[0].strip()

    return peer_ip


def truncate_ip(raw_ip: str) -> Tuple[str, str]:
    """Truncate IP to /24 (IPv4) or /64 (IPv6) and generate privacy-masked display string.
    
    The raw IP address is discarded immediately; only prefix and masked strings are stored.
    Returns: (network_prefix, masked_ip)
    Examples:
      '103.45.67.89' -> ('103.45.67.0/24', '103.45.67.x')
      '2001:db8:85a3::8a2e:370:7334' -> ('2001:db8:85a3::/64', '2001:db8:85a3:x::x')
    """
    clean_ip = (raw_ip or "127.0.0.1").strip()
    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.version == 4:
            net = ipaddress.ip_network(f"{clean_ip}/24", strict=False)
            parts = str(ip_obj).split(".")
            masked = f"{parts[0]}.{parts[1]}.{parts[2]}.x"
            return str(net), masked
        else:
            net = ipaddress.ip_network(f"{clean_ip}/64", strict=False)
            masked = f"{net.network_address}x"
            return str(net), masked
    except Exception:
        return "127.0.0.0/24", "127.0.0.x"


def generate_session_token() -> str:
    """Generate unguessable 48-char hex session token for participant authentication."""
    return secrets.token_hex(24)


def generate_join_token() -> str:
    """Generate unguessable URL-safe token required to join a specific room."""
    return secrets.token_urlsafe(16)


def is_public_host(host_header: str, forwarded_host: Optional[str] = None) -> bool:
    """Determine whether request arrives via public tunnel (Cloudflare quick tunnel, ngrok, etc.)."""
    effective_host = (forwarded_host or host_header or "").lower().split(":")[0].strip()
    
    # Known local / private host names
    local_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "testserver",
    }
    
    if not effective_host or effective_host in local_hosts:
        return False

    # LAN IP addresses (192.168.x.x, 10.x.x.x, 172.16-31.x.x) are local Wi-Fi, not public tunnel
    try:
        ip_obj = ipaddress.ip_address(effective_host)
        if ip_obj.is_private or ip_obj.is_loopback:
            return False
    except ValueError:
        pass

    # Anything else (e.g. *.trycloudflare.com, *.ngrok-free.app, external domains) is public
    return True


# Strict allowlist of route patterns permissible through the public tunnel
PUBLIC_ALLOWLIST_EXACT = {
    "/app",
    "/app/",
    "/vite.svg",
    "/favicon.ico",
    "/api/v1/live/transfer",
}

PUBLIC_ALLOWLIST_PREFIXES = (
    "/assets/",
    "/api/v1/live/rooms/",
)

PUBLIC_ALLOWED_ROOM_SUBPATHS = {
    "join",
    "me",
    "recipients",
    "join-info",
}


def is_route_publicly_allowed(path: str, method: str = "GET") -> bool:
    """Check whether a route is accessible over the public tunnel.
    
    When ALLOW_FULL_PUBLIC_ACCESS is 'true', the entire website (Analyst Console,
    Demo Studio, Graph, Model Performance, Case Queue, Customer App) is accessible.
    When set to 'false' (strict participant mode), ONLY participant mobile routes
    (/app, join, transfer, me, recipients, own events) are accessible.
    """
    import os
    if os.getenv("ALLOW_FULL_PUBLIC_ACCESS", "true").lower() in ("true", "1", "yes"):
        return True

    clean_path = path.split("?")[0].rstrip("/")
    if not clean_path:
        clean_path = "/"

    if clean_path in ("/app", "/vite.svg", "/favicon.ico"):
        return True

    if clean_path.startswith("/assets/"):
        return True

    if clean_path == "/api/v1/live/transfer" and method.upper() == "POST":
        return True

    if clean_path.startswith("/api/v1/live/rooms/"):
        parts = [p for p in clean_path.split("/") if p]
        # Pattern 1: /api/v1/live/rooms/{room_code}/[join | me | recipients | join-info]
        # parts: ["api", "v1", "live", "rooms", "{room_code}", "{sub}"] -> len == 6
        if len(parts) == 6:
            sub = parts[5]
            if sub in PUBLIC_ALLOWED_ROOM_SUBPATHS:
                if sub == "join" and method.upper() == "POST":
                    return True
                if sub in ("me", "recipients", "join-info") and method.upper() == "GET":
                    return True

        # Pattern 2: /api/v1/live/rooms/{room_code}/participants/{account_id}/events
        # parts: ["api", "v1", "live", "rooms", "{room_code}", "participants", "{account_id}", "events"] -> len == 8
        if len(parts) == 8 and parts[5] == "participants" and parts[7] == "events":
            if method.upper() == "GET":
                return True

    return False
