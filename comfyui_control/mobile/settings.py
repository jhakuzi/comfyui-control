"""App-wide mobile preferences, independent of installation launch settings."""
from dataclasses import asdict, dataclass, fields
import hashlib
import hmac
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
import socket
import tempfile
from urllib.parse import urlsplit

from ..config import config_path


def data_dir():
    return config_path().parent / "mobile"


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".saving-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def password_hash(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 256:
        raise ValueError("Use a mobile password between 10 and 256 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return salt + ":" + digest.hex()


def check_password(password, stored):
    try:
        salt, digest = stored.split(":")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, AttributeError):
        return False


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # Route lookup; no packet is sent.
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def url_host(value):
    value = value.strip("[]")
    try:
        address = ipaddress.ip_address(value)
        return "[" + str(address) + "]" if address.version == 6 else str(address)
    except ValueError:
        try:
            host = value.encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("Invalid advertised hostname.") from None
        if len(host) > 253 or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.rstrip('.').split('.')):
            raise ValueError("Enter a valid advertised hostname or IP (without a port), or a full HTTP(S) origin.")
        return host


@dataclass
class MobileSettings:
    enabled: bool = False
    bind: str = "0.0.0.0"
    port: int = 8189
    advertised: str = ""
    comfy_url: str = "http://127.0.0.1:8188"
    require_auth: bool = False
    password: str = ""  # Salted PBKDF2 hash, never a plaintext password.
    default_preset: str = ""
    preferences_version: int = 1

    @classmethod
    def load(cls, path=None):
        path = path or data_dir() / "settings.json"
        if not Path(path).exists():
            return cls()
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict):
            raise ValueError("Mobile settings must be a JSON object.")
        result = cls(**{k: v for k, v in value.items() if k in {f.name for f in fields(cls)}})
        if "preferences_version" not in value:
            # Upgrade the old defaults; explicit custom addresses and passwords stay.
            if result.bind == "127.0.0.1" and not result.advertised:
                result.bind = "0.0.0.0"
            if not result.password:
                result.require_auth = False
        result.validate(require_password=False)
        return result

    def validate(self, require_password=True):
        if type(self.enabled) is not bool or type(self.require_auth) is not bool:
            raise ValueError("Invalid mobile enable/authentication setting.")
        if type(self.preferences_version) is not int or self.preferences_version < 1:
            raise ValueError("Invalid mobile preferences version.")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Choose a mobile port between 1024 and 65535.")
        for value in (self.bind, self.advertised, self.comfy_url, self.password, self.default_preset):
            if not isinstance(value, str):
                raise ValueError("Invalid mobile text setting.")
        try:
            ipaddress.ip_address(self.bind)
        except ValueError:
            raise ValueError("Listening address must be an IP, such as 127.0.0.1, 0.0.0.0, or a VPN interface IP.") from None
        if self.default_preset and not re.fullmatch(r"[0-9a-f]{32}", self.default_preset):
            raise ValueError("Choose a saved default mobile workflow.")
        if self.enabled and self.require_auth and require_password and not self.password:
            raise ValueError("Set a mobile password before enabling the server.")
        upstream = urlsplit(self.comfy_url)
        if upstream.scheme not in ("http", "https") or not upstream.hostname or upstream.username or upstream.password or upstream.query or upstream.fragment:
            raise ValueError("Enter a ComfyUI HTTP(S) URL without credentials or query parameters.")
        self.url()

    def url(self):
        value = self.advertised.strip()
        if self.bind == "::" and not value:
            raise ValueError("Set an advertised IPv6 address or VPN hostname when listening on ::.")
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
                raise ValueError("Advertised URL must be an HTTP(S) origin without a path, password, or query.")
            try:
                parsed.port
            except ValueError:
                raise ValueError("Invalid advertised URL port.") from None
            host = url_host(parsed.hostname)
            return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "") + "/"
        host = value or (lan_address() if self.bind in ("0.0.0.0", "::") else self.bind)
        if not host or any(c in host for c in "/@?#\\ \t\r\n"):
            raise ValueError("Enter an advertised hostname/IP, or a full HTTP(S) origin.")
        host = url_host(host)
        return f"http://{host}:{self.port}/"

    def save(self, path=None):
        self.validate()
        save_json(path or data_dir() / "settings.json", asdict(self))
