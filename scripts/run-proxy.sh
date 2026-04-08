#!/usr/bin/env bash
cd "$(dirname "$0")/../backend"
./cloud-sql-proxy.exe samba-wave-molle:asia-northeast3:samba-wave-db --port 5433
exec bash
