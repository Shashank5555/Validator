from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SFTPConfig:
    host: str
    port: int
    username: str
    password: str
    remote_dir: str = "/upload"
    known_hosts: Optional[str] = None


class SFTPClient:
    def __init__(self, config: SFTPConfig):
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ensure_exists(self, filename: str) -> str:
        raise NotImplementedError("SFTP access is not configured in this deployment.")

    def fetch_bytes(self, remote_path: str) -> bytes:
        raise NotImplementedError("SFTP access is not configured in this deployment.")
