"""Mobile shell pairing and remote-control API."""

from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import platform
import secrets
import socket
import string
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from open_agent.utils.path_utils import get_data_dir

router = APIRouter(prefix="/api/mobile", tags=["mobile"])

PAIRING_TTL_SECONDS = 180
TOKEN_BYTES = 32
PAIRING_CODE_LENGTH = 6
PAIRING_ATTEMPT_WINDOW_SECONDS = 60
PAIRING_MAX_FAILED_ATTEMPTS = 8


@dataclass
class PairingCode:
    code: str
    expires_at: datetime


_pairing_code: PairingCode | None = None
_config_lock = threading.RLock()
_network_cache: tuple[float, list[str]] = (0.0, [])
_pairing_attempts: dict[str, list[float]] = {}


class MobileCreateChatRequest(BaseModel):
    name: str = "Mobile Chat"
    profile_id: str = "main"


def _profile_manager_id(profile_id: str | None) -> str | None:
    normalized = str(profile_id or "main").strip()
    return None if not normalized or normalized == "main" else normalized


def _mobile_config_path() -> Path:
    path = get_data_dir() / "mobile" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_config() -> dict[str, Any]:
    with _config_lock:
        path = _mobile_config_path()
        if not path.exists():
            return {"devices": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"devices": []}
        data.setdefault("devices", [])
        return data


def _write_config(config: dict[str, Any]) -> None:
    with _config_lock:
        path = _mobile_config_path()
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)


def _now() -> datetime:
    return datetime.now()


def _public_device(device: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in device.items()
        if key not in {"token", "token_hash"}
    }


def _generate_pairing_code() -> PairingCode:
    alphabet = string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(PAIRING_CODE_LENGTH))
    return PairingCode(code=code, expires_at=_now() + timedelta(seconds=PAIRING_TTL_SECONDS))


def _get_pairing_code() -> PairingCode:
    global _pairing_code
    if _pairing_code is None or _pairing_code.expires_at <= _now():
        _pairing_code = _generate_pairing_code()
    return _pairing_code


def _consume_pairing_code(code: str) -> bool:
    global _pairing_code
    current = _pairing_code
    if not current or current.expires_at <= _now() or current.code != str(code).strip():
        return False
    _pairing_code = None
    return True


def _pairing_client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_pairing_rate_limit(request: Request) -> str:
    client_key = _pairing_client_key(request)
    now = time.monotonic()
    attempts = [
        attempted_at
        for attempted_at in _pairing_attempts.get(client_key, [])
        if now - attempted_at < PAIRING_ATTEMPT_WINDOW_SECONDS
    ]
    _pairing_attempts[client_key] = attempts
    if len(attempts) >= PAIRING_MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed pairing attempts. Try again in one minute.",
        )
    return client_key


def _record_failed_pairing(client_key: str) -> None:
    _pairing_attempts.setdefault(client_key, []).append(time.monotonic())


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in {"localhost", "tauri.localhost", "testclient"}


def _require_local_request(request: Request) -> None:
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="This mobile pairing endpoint is only available locally")


def _is_lan_ipv4(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if not isinstance(ip, ipaddress.IPv4Address) or ip.is_loopback or ip.is_link_local:
        return False
    return any(
        ip in network
        for network in (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
    )


def _windows_network_addresses() -> list[str]:
    if platform.system() != "Windows":
        return []
    script = (
        "Get-NetIPConfiguration | "
        "Where-Object { $_.NetAdapter.Status -eq 'Up' -and $_.IPv4Address } | "
        "ForEach-Object { [PSCustomObject]@{"
        "Address=$_.IPv4Address.IPAddress;"
        "Gateway=(@($_.IPv4DefaultGateway.NextHop) -join ',');"
        "Hardware=$_.NetAdapter.HardwareInterface;"
        "Alias=$_.InterfaceAlias"
        "} } | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        raw = json.loads(result.stdout)
        entries = raw if isinstance(raw, list) else [raw]
    except Exception:
        return []

    virtual_terms = ("virtual", "vethernet", "vmware", "hyper-v", "tailscale", "zerotier", "wsl")
    ranked: list[tuple[tuple[int, int, int, str], str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        address = str(entry.get("Address") or "")
        if not _is_lan_ipv4(address):
            continue
        alias = str(entry.get("Alias") or "")
        rank = (
            0 if entry.get("Gateway") else 1,
            0 if entry.get("Hardware") is True else 1,
            1 if any(term in alias.lower() for term in virtual_terms) else 0,
            address,
        )
        ranked.append((rank, address))
    return [address for _, address in sorted(ranked)]


def _local_ipv4_addresses() -> list[str]:
    global _network_cache
    cached_at, cached_addresses = _network_cache
    if cached_addresses and time.monotonic() - cached_at < 30:
        return list(cached_addresses)

    addresses: set[str] = set()
    preferred = _windows_network_addresses()
    addresses.update(preferred)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            route_address = sock.getsockname()[0]
            if _is_lan_ipv4(route_address):
                addresses.add(route_address)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = item[4][0]
            if _is_lan_ipv4(address):
                addresses.add(address)
    except Exception:
        pass

    fallback_addresses = sorted(
        addresses.difference(preferred),
        key=lambda address: (
            1 if address.rsplit(".", 1)[-1] == "1" else 0,
            address,
        ),
    )
    ordered = preferred + fallback_addresses
    _network_cache = (time.monotonic(), ordered)
    return ordered


def _request_port(request: Request) -> int:
    if request.url.port:
        return int(request.url.port)
    return 443 if request.url.scheme == "https" else 80


def _configured_bind_host() -> str:
    env_host = str(os.environ.get("OPEN_AGENT_DESKTOP_HOST") or "").strip()
    if env_host:
        return env_host
    for index, argument in enumerate(sys.argv):
        if argument == "--host" and index + 1 < len(sys.argv):
            return str(sys.argv[index + 1]).strip()
        if argument.startswith("--host="):
            return argument.split("=", 1)[1].strip()
    return "127.0.0.1"


def _mobile_urls(request: Request, code: str | None = None) -> list[str]:
    port = _request_port(request)
    suffix = f"/mobile?code={code}" if code else "/mobile"
    urls = [f"{request.url.scheme}://127.0.0.1:{port}{suffix}"]
    for address in _local_ipv4_addresses():
        urls.append(f"{request.url.scheme}://{address}:{port}{suffix}")
    return urls


def _extract_token(authorization: str | None = None, token: str | None = None) -> str:
    if token:
        return token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _device_matches_token(device: dict[str, Any], token: str) -> bool:
    stored_hash = str(device.get("token_hash") or "")
    if stored_hash:
        return secrets.compare_digest(stored_hash, _token_hash(token))
    legacy_token = str(device.get("token") or "")
    return bool(legacy_token) and secrets.compare_digest(legacy_token, token)


def validate_mobile_token(token: str) -> dict[str, Any] | None:
    token = str(token or "").strip()
    if not token:
        return None
    config = _read_config()
    for device in config.get("devices", []):
        if device.get("enabled", True) and _device_matches_token(device, token):
            try:
                last_seen = datetime.fromisoformat(device["last_seen_at"]) if device.get("last_seen_at") else None
            except (TypeError, ValueError):
                last_seen = None
            if last_seen is None or (_now() - last_seen).total_seconds() >= 30:
                device["last_seen_at"] = _now().isoformat()
                if device.get("token") and not device.get("token_hash"):
                    device["token_hash"] = _token_hash(token)
                    device.pop("token", None)
                _write_config(config)
            return device
    return None


def _is_mobile_remote_path_allowed(request: Request) -> bool:
    path = request.url.path
    if request.method == "OPTIONS":
        return True
    if path == "/api/health":
        return True
    if path.startswith("/api/mobile/"):
        return True
    if request.method == "POST" and path in {"/api/run", "/api/cancel"}:
        return True
    return False


def is_remote_api_request_allowed(request: Request) -> bool:
    if not request.url.path.startswith("/api/"):
        return True
    if _is_loopback(request.client.host if request.client else None):
        return True
    if request.method == "OPTIONS":
        return True
    if request.url.path.startswith("/api/mobile/") or request.url.path == "/api/health":
        return True
    if not _is_mobile_remote_path_allowed(request):
        return False
    token = _extract_token(request.headers.get("authorization"), request.query_params.get("mobile_token"))
    return validate_mobile_token(token) is not None


def _require_mobile_device(authorization: str | None, token: str | None) -> dict[str, Any]:
    device = validate_mobile_token(_extract_token(authorization, token))
    if not device:
        raise HTTPException(status_code=401, detail="Invalid or missing mobile token")
    return device


async def _list_agents() -> list[dict[str, Any]]:
    from open_agent.agent_profiles import get_agent_profile_manager

    manager = get_agent_profile_manager()
    agents = [manager.get_main_agent().to_dict()]
    agents.extend(profile.to_dict() for profile in manager.list_profiles())
    return agents


async def _list_recent_chats(profile_id: str = "main", limit: int = 20) -> list[dict[str, Any]]:
    from open_agent.app.runner import get_chat_manager

    manager = get_chat_manager(_profile_manager_id(profile_id))
    chats = await manager.list_chats()
    result = []
    for chat in chats[:limit]:
        result.append(
            {
                "id": chat.id,
                "name": chat.name,
                "session_id": chat.session_id,
                "updated_at": chat.updated_at.isoformat(),
                "created_at": chat.created_at.isoformat(),
                "channel": chat.channel,
                "meta": chat.meta,
                "profile_id": profile_id or "main",
            }
        )
    return result


def _list_running_tasks() -> list[dict[str, Any]]:
    try:
        from open_agent.task_queue import get_task_dispatcher

        dispatcher = get_task_dispatcher()
        if not dispatcher:
            return []
        return [task.to_dict() for task in dispatcher.get_running_tasks()]
    except Exception:
        return []


@router.get("/access-info")
async def access_info(request: Request) -> dict[str, Any]:
    _require_local_request(request)
    config = _read_config()
    bind_host = _configured_bind_host()
    return {
        "success": True,
        "mobile_path": "/mobile",
        "bind_host": bind_host,
        "remote_enabled": bind_host not in {"127.0.0.1", "localhost"},
        "local_urls": _mobile_urls(request),
        "lan_urls": [url for url in _mobile_urls(request) if "127.0.0.1" not in url],
        "pairing_ttl_seconds": PAIRING_TTL_SECONDS,
        "paired_devices": [
            {
                "id": device.get("id"),
                "name": device.get("name"),
                "created_at": device.get("created_at"),
                "last_seen_at": device.get("last_seen_at"),
                "enabled": device.get("enabled", True),
            }
            for device in config.get("devices", [])
        ],
    }


@router.post("/pairing-code")
async def pairing_code(request: Request) -> dict[str, Any]:
    _require_local_request(request)
    code = _get_pairing_code()
    urls = _mobile_urls(request, code.code)
    return {
        "success": True,
        "code": code.code,
        "expires_at": code.expires_at.isoformat(),
        "mobile_url": next((url for url in urls if "127.0.0.1" not in url), urls[0]),
        "mobile_urls": urls,
    }


@router.post("/pair")
async def pair_device(data: dict[str, Any], request: Request) -> dict[str, Any]:
    client_key = _check_pairing_rate_limit(request)
    code = str(data.get("code") or "").strip()
    if not _consume_pairing_code(code):
        _record_failed_pairing(client_key)
        raise HTTPException(status_code=401, detail="Invalid or expired pairing code")
    _pairing_attempts.pop(client_key, None)

    config = _read_config()
    raw_token = secrets.token_urlsafe(TOKEN_BYTES)
    device = {
        "id": f"mobile_{uuid.uuid4().hex[:12]}",
        "name": str(data.get("device_name") or "Mobile Device").strip()[:80],
        "token_hash": _token_hash(raw_token),
        "created_at": _now().isoformat(),
        "last_seen_at": _now().isoformat(),
        "enabled": True,
    }
    config.setdefault("devices", []).append(device)
    _write_config(config)
    return {
        "success": True,
        "device": _public_device(device),
        "token": raw_token,
    }


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, request: Request) -> dict[str, Any]:
    _require_local_request(request)
    config = _read_config()
    devices = config.get("devices", [])
    remaining = [device for device in devices if str(device.get("id")) != device_id]
    if len(remaining) == len(devices):
        raise HTTPException(status_code=404, detail="Mobile device not found")
    config["devices"] = remaining
    _write_config(config)
    return {"success": True, "device_id": device_id}


@router.get("/summary")
async def mobile_summary(
    authorization: str | None = Header(default=None),
    token: str | None = None,
    profile_id: str = Query(default="main"),
) -> dict[str, Any]:
    device = _require_mobile_device(authorization, token)
    return {
        "success": True,
        "device": _public_device(device),
        "agents": await _list_agents(),
        "chats": await _list_recent_chats(profile_id=profile_id),
        "running_tasks": _list_running_tasks(),
        "server_time": _now().isoformat(),
    }


@router.post("/chats")
async def create_mobile_chat(
    data: MobileCreateChatRequest,
    authorization: str | None = Header(default=None),
    token: str | None = None,
) -> dict[str, Any]:
    _require_mobile_device(authorization, token)
    from open_agent.app.runner import get_chat_manager

    manager = get_chat_manager(_profile_manager_id(data.profile_id))
    chat = await manager.create_chat(
        name=data.name,
        user_id="mobile",
        channel="mobile",
    )
    return {
        "id": chat.id,
        "name": chat.name,
        "session_id": chat.session_id,
        "user_id": chat.user_id,
        "channel": chat.channel,
        "meta": chat.meta,
        "profile_id": data.profile_id or "main",
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


@router.get("/chats/{chat_id}/history")
async def mobile_chat_history(
    chat_id: str,
    authorization: str | None = Header(default=None),
    token: str | None = None,
    profile_id: str = Query(default="main"),
) -> dict[str, Any]:
    _require_mobile_device(authorization, token)
    from open_agent.app.runner import get_chat_manager

    history = await get_chat_manager(_profile_manager_id(profile_id)).get_history(chat_id)
    if not history:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "success": True,
        "chat_id": history.chat_id,
        "total": history.total,
        "messages": [message.to_api_format() for message in history.messages],
    }
