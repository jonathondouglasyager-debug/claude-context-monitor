"""
Convergence Engine - Atomic File Operations

Provides atomic append and update for JSONL files using the `filelock`
library for cross-process safe locking. Replaces previous fcntl-based
implementation which was advisory-only and insufficient for concurrent
Claude sessions.

Phase 2 upgrade: filelock library with 20 retries, 2s max backoff cap.
"""

import json
import os
import tempfile
import time
from typing import Optional

from filelock import FileLock, Timeout


class FileLockError(Exception):
    """Raised when a file lock cannot be acquired after retries."""
    pass


class AtomicAppendError(Exception):
    """Raised when atomic append fails after temp write."""
    pass


# Lock configuration
_MAX_RETRIES = 20
_MAX_BACKOFF = 2.0  # seconds
_LOCK_TIMEOUT = 10  # seconds per attempt


def _get_lock(filepath: str) -> FileLock:
    """
    Get a FileLock instance for the given data file.

    Uses a .lock sidecar file in the same directory.
    """
    lock_path = filepath + ".lock"
    return FileLock(lock_path, timeout=_LOCK_TIMEOUT)


def atomic_append(filepath: str, record: dict, max_retries: int = _MAX_RETRIES, retry_delay: float = 0.1) -> None:
    """
    Atomically append a JSON record as a single line to a JSONL file.

    Uses filelock for cross-process safe locking.

    Args:
        filepath: Path to the .jsonl file
        record: Dictionary to serialize and append
        max_retries: Number of lock acquisition retries
        retry_delay: Initial seconds between retries (doubles each attempt, capped at 2s)
    """
    # Validate JSON serialization first (fail fast before any I/O)
    try:
        line = json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise AtomicAppendError(f"Record is not JSON-serializable: {e}")

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    lock = _get_lock(filepath)
    current_delay = retry_delay

    for attempt in range(max_retries):
        try:
            with lock:
                with open(filepath, "a", encoding="utf-8") as data_fd:
                    data_fd.write(line + "\n")
                    data_fd.flush()
                    os.fsync(data_fd.fileno())
                return  # Success

        except Timeout:
            if attempt < max_retries - 1:
                time.sleep(current_delay)
                current_delay = min(current_delay * 2, _MAX_BACKOFF)
                continue
            raise FileLockError(
                f"Could not acquire lock on {filepath}.lock after {max_retries} retries. "
                f"Another process may be holding the lock."
            )
        except Exception as e:
            raise AtomicAppendError(f"Failed to append to {filepath}: {e}")


def read_jsonl(filepath: str) -> list[dict]:
    """
    Read all records from a JSONL file.
    Skips and logs corrupt lines rather than failing entirely.

    Returns:
        List of parsed dictionaries
    """
    records = []
    if not os.path.exists(filepath):
        return records

    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # Log but don't fail -- corrupt line isolation
                import sys
                print(
                    f"[WARN] Corrupt JSONL at {filepath}:{line_num} -- skipping",
                    file=sys.stderr
                )
    return records


def read_jsonl_by_id(filepath: str, record_id: str, id_field: str = "id") -> Optional[dict]:
    """
    Find a single record by its ID field.

    Args:
        filepath: Path to JSONL file
        record_id: Value to match against id_field
        id_field: Name of the ID field in the record

    Returns:
        Matching record dict or None
    """
    for record in read_jsonl(filepath):
        if record.get(id_field) == record_id:
            return record
    return None


def update_jsonl_record(filepath: str, record_id: str, updates: dict, id_field: str = "id") -> bool:
    """
    Update a specific record in a JSONL file by rewriting the file atomically.

    Uses filelock for cross-process safety.

    Args:
        filepath: Path to JSONL file
        record_id: ID of record to update
        updates: Dictionary of field updates to apply
        id_field: Name of the ID field

    Returns:
        True if record was found and updated, False otherwise
    """
    if not os.path.exists(filepath):
        return False

    lock = _get_lock(filepath)

    try:
        with lock:
            records = []
            found = False

            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get(id_field) == record_id:
                            record.update(updates)
                            found = True
                        records.append(record)
                    except json.JSONDecodeError:
                        records.append(None)  # Preserve line count

            if found:
                # Write to temp file, then rename for atomicity
                dir_name = os.path.dirname(filepath) or "."
                tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".jsonl.tmp")
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_f:
                        for record in records:
                            if record is not None:
                                tmp_f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                    os.replace(tmp_path, filepath)
                except Exception:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                    raise

            return found

    except Timeout:
        raise FileLockError(f"Could not acquire lock to update {filepath}")
    except FileLockError:
        raise
    except Exception as e:
        raise AtomicAppendError(f"Failed to update record in {filepath}: {e}")
