"""현재 .env 가 가리키는 DB 가 production 인지 확인."""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.config import settings

host = settings.write_db_host
port = settings.write_db_port
name = settings.write_db_name
user = settings.write_db_user
print(f"host={host}")
print(f"port={port}")
print(f"db_name={name}")
print(f"user={user}")
print(f"is_localhost={'YES' if host in ('localhost','127.0.0.1') else 'NO'}")
