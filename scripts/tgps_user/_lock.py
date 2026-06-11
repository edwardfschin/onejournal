#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/_lock.py
Version: 0.1.1 (2026-01-14, SGT)

Purpose
-------
Single-writer, cross-process lock helper (file lock) for DuckDB write safety.

Design goals
------------
- Fail-fast by default (no indefinite waits).
- Lock file sits next to the target DB (or any chosen lock path).
- Human-readable JSON metadata inside lock file.
- Stale-lock handling with TTL + (best-effort) PID-alive check on same host.

Usage (writers)
---------------
from ._lock import ledger_write_lock

with ledger_write_lock(ledger_db_path, run_id=os.getenv("TGPS_RUN_ID"), step="fills_mgt.sync"):
    # do DuckDB writes safely here

Or generic:
from ._lock import FileLock

with FileLock("/path/to/some.lock", meta={"run_id": "...", "step": "..."}):
    ...

Environment knobs (optional)
---------------------------
- TGPS_LOCK_TTL_SECS     : stale lock threshold (default 1200 = 20 min)
- TGPS_LOCK_WAIT_SECS    : if >0, retry until timeout (default 0 = fail-fast)
- TGPS_LOCK_POLL_SECS    : retry polling interval (default 0.5)

Notes
-----
- This module is intentionally dependency-free.
- Read-only commands should NOT acquire the lock.

Change log
----------
0.1.1
- Treat invalid/empty lock metadata as stale based on lock file mtime (prevents wedged locks).
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class LockHeldError(RuntimeError):
    """Raised when a lock is currently held and not considered stale."""
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _pid_alive(pid: int) -> bool:
    """
    Best-effort: On Unix/macOS, os.kill(pid, 0) checks existence without killing.
    Returns False if pid is not alive or check isn't permitted.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission; treat as alive to be safe.
        return True
    except Exception:
        return False


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _write_json_fd(fd: int, payload: Dict[str, Any]) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    os.write(fd, data)
    os.fsync(fd)


def _age_seconds(started_at_epoch: Optional[float]) -> Optional[float]:
    if started_at_epoch is None:
        return None
    try:
        return max(0.0, time.time() - float(started_at_epoch))
    except Exception:
        return None


def _file_age_seconds(path: str) -> Optional[float]:
    """
    Fallback age based on filesystem mtime.
    Used when metadata is missing/invalid (e.g. crash before JSON write).
    """
    try:
        mtime = os.path.getmtime(path)
        return max(0.0, time.time() - float(mtime))
    except Exception:
        return None


@dataclass
class LockInfo:
    path: str
    meta: Dict[str, Any]

    @property
    def pid(self) -> int:
        return _safe_int(self.meta.get("pid"), -1)

    @property
    def host(self) -> str:
        return str(self.meta.get("host") or "")

    @property
    def started_at_epoch(self) -> Optional[float]:
        v = self.meta.get("started_at_epoch")
        try:
            return float(v) if v is not None else None
        except Exception:
            return None

    @property
    def age_seconds(self) -> Optional[float]:
        return _age_seconds(self.started_at_epoch)

    @property
    def run_id(self) -> str:
        return str(self.meta.get("tgps_run_id") or "")

    @property
    def step(self) -> str:
        return str(self.meta.get("tgps_step") or "")

    def describe_one_line(self) -> str:
        age = self.age_seconds
        age_s = f"{age:.1f}s" if isinstance(age, (float, int)) else "unknown"
        return f"lock={self.path} pid={self.pid} host={self.host} age={age_s} run_id={self.run_id} step={self.step}"


class FileLock:
    """
    Simple cross-process file lock using atomic create (O_CREAT|O_EXCL).

    If lock exists:
      - If stale => attempt to quarantine/replace it.
      - Else => raise LockHeldError (or retry if wait_seconds > 0).
    """

    def __init__(
        self,
        path: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
        wait_seconds: Optional[int] = None,
        poll_seconds: Optional[float] = None,
    ) -> None:
        self.path = os.path.abspath(path)
        self.meta = dict(meta or {})
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _safe_int(os.getenv("TGPS_LOCK_TTL_SECS"), 1200)
        self.wait_seconds = wait_seconds if wait_seconds is not None else _safe_int(os.getenv("TGPS_LOCK_WAIT_SECS"), 0)
        self.poll_seconds = poll_seconds if poll_seconds is not None else float(os.getenv("TGPS_LOCK_POLL_SECS", "0.5"))
        self._acquired = False
        self._owner_token = f"{os.getpid()}@{socket.gethostname()}:{time.time():.6f}"

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def is_acquired(self) -> bool:
        return self._acquired

    def info(self) -> LockInfo:
        return LockInfo(self.path, _read_json(self.path))

    def acquire(self) -> None:
        deadline = time.time() + max(0, int(self.wait_seconds))
        first_attempt = True

        while True:
            try:
                self._try_acquire_once()
                self._acquired = True
                return
            except LockHeldError:
                if self.wait_seconds <= 0:
                    raise
                if time.time() >= deadline and not first_attempt:
                    raise
                first_attempt = False
                time.sleep(max(0.05, float(self.poll_seconds)))

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        finally:
            self._acquired = False

    def _try_acquire_once(self) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        mode = 0o644

        try:
            fd = os.open(self.path, flags, mode)
        except FileExistsError:
            existing = self.info()
            if self._is_stale(existing):
                self._quarantine_stale(existing)
                try:
                    fd = os.open(self.path, flags, mode)
                except FileExistsError:
                    existing2 = self.info()
                    raise LockHeldError(f"Lock held: {existing2.describe_one_line()}")
            else:
                raise LockHeldError(f"Lock held: {existing.describe_one_line()}")

        try:
            payload = self._build_payload()
            _write_json_fd(fd, payload)
        finally:
            try:
                os.close(fd)
            except Exception:
                pass

    def _build_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started_at_utc": _utc_now_iso(),
            "started_at_epoch": time.time(),
            "argv": " ".join([repr(a) for a in (os.sys.argv or [])])[:2000],
            "owner_token": self._owner_token,
        }
        for k, v in (self.meta or {}).items():
            payload[k] = v
        return payload

    def _is_stale(self, existing: LockInfo) -> bool:
        # Prefer metadata-based age
        age = existing.age_seconds

        # If metadata is missing/invalid, fall back to file mtime age
        if age is None:
            age = _file_age_seconds(existing.path)

        if age is None:
            return False
        if age < float(self.ttl_seconds):
            return False

        # TTL exceeded. If same host and we have a pid, try pid-alive check.
        my_host = socket.gethostname()
        if existing.host and existing.host == my_host and existing.pid > 0:
            return not _pid_alive(existing.pid)

        # Different host / unknown host / unknown pid: TTL-only stale policy.
        return True

    def _quarantine_stale(self, existing: LockInfo) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stale_path = f"{self.path}.stale.{ts}.pid{existing.pid}"
        try:
            os.replace(self.path, stale_path)
        except FileNotFoundError:
            return
        except Exception:
            raise LockHeldError(f"Lock held (stale quarantine failed): {existing.describe_one_line()}")


def ledger_write_lock(
    ledger_db_path: str,
    *,
    run_id: Optional[str] = None,
    step: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    wait_seconds: Optional[int] = None,
) -> FileLock:
    """
    Convenience wrapper: place the lock next to the ledger DB file.
    Caller must pass the correct ledger_db_path (no guessing here).
    """
    db_path = os.path.abspath(str(ledger_db_path))
    lock_path = os.path.join(os.path.dirname(db_path), "tgps_ledger_write.lock")

    meta: Dict[str, Any] = {
        "tgps_run_id": run_id or os.getenv("TGPS_RUN_ID", ""),
        "tgps_step": step or os.getenv("TGPS_STEP", ""),
        "lock_for": os.path.basename(db_path),
    }
    return FileLock(
        lock_path,
        meta=meta,
        ttl_seconds=ttl_seconds,
        wait_seconds=wait_seconds,
    )


def doctor_lock_check(lock_path: str) -> Dict[str, Any]:
    """
    Quick healthcheck: acquire + release lock.
    Returns a dict suitable for printing in doctor output.
    """
    path = os.path.abspath(lock_path)
    result: Dict[str, Any] = {"lock_path": path}

    try:
        with FileLock(path, meta={"tgps_step": "doctor.lock_check"}):
            result["ok"] = True
            result["detail"] = "acquired_and_released"
    except LockHeldError as e:
        result["ok"] = False
        result["detail"] = str(e)
    except Exception as e:
        result["ok"] = False
        result["detail"] = f"unexpected_error: {e}"

    return result
