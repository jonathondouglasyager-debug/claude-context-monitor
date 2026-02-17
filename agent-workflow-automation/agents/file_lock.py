"""
Convergence Engine - Atomic File Operations

Provides atomic append for JSONL files using temp-file-rename pattern
with fcntl file locking to prevent concurrent write corruption.
"""

import fcntl
import json
import os
import tempfile
import time
from typing import Optional


class FileLockError(Exception):
    """Raised when a file lock cannot be acquired after retries."""
    pass


class AtomicAppendError(Exception):
    """Raised when atomic append fails after temp write."""
    pass


def atomic_append(filepath: str, record: dict, max_retries: int = 10, retry_delay: float = 0.1) -> None:
    """
    Atomically append a JSON record as a single line to a JSONL file.

    Strategy:
    1. Acquire an exclusive lock on the target file (or a .lock sidecar)
    2. Validate the record serializes to valid JSON
    3. Write to a temp file in the same directory
    4. Read existing content, append new line, write back
    5. Release lock

    Using flock + direct append (not rename) because JSONL is append-only
    and rename would lose existing records.

    Args:
        filepath: Path to the .jsonl file
        record: Dictionary to serialize and append
        max_retries: Number of lock acquisition retries
        retry_delay: Seconds between retries (doubles each attempt)
    """
    # Validate JSON serialization first (fail fast before any I/O)
    try:
        line = json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise AtomicAppendError(f"Record is not JSON-serializable: {e}")

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    # Use a sidecar lock file to avoid issues with locking the data file itself
    lock_path = filepath + ".lock"

    attempt = 0
    current_delay = retry_delay

    while attempt < max_retries:
        lock_fd = None
        try:
            # Open or create lock file
            lock_fd = open(lock_path, "w")

            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Lock acquired -- append the record
            with open(filepath, "a", encoding="utf-8") as data_fd:
                data_fd.write(line + "\n")
                data_fd.flush()
                os.fsync(data_fd.fileno())

            # Success -- release lock and return
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            return

        except BlockingIOError:
            # Lock is held by another process -- retry with backoff
            if lock_fd:
                lock_fd.close()
            attempt += 1
            if attempt < max_retries:
                time.sleep(current_delay)
                current_delay *= 2  # Exponential backoff
            continue

        except Exception as e:
            # Unexpected error -- clean up and raise
            if lock_fd:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    lock_fd.close()
                except Exception:
                    pass
            raise AtomicAppendError(f"Failed to append to {filepath}: {e}")

    raise FileLockError(
        f"Could not acquire lock on {lock_path} after {max_retries} retries. "
        f"Another process may be holding the lock."
    )


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

    lock_path = filepath + ".lock"
    lock_fd = None

    try:
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

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
                # Clean up temp file on failure
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()
        return found

    except Exception as e:
        if lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
            except Exception:
                pass
        raise AtomicAppendError(f"Failed to update record in {filepath}: {e}")
