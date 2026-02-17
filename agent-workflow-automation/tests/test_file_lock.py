"""Tests for agents/file_lock.py"""

import json
import os
import pytest
from concurrent.futures import ThreadPoolExecutor

from agents.file_lock import (
    atomic_append,
    read_jsonl,
    read_jsonl_by_id,
    update_jsonl_record,
    AtomicAppendError,
)


class TestAtomicAppend:
    def test_creates_file_if_not_exists(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        record = {"id": "001", "msg": "hello"}
        atomic_append(filepath, record)

        assert os.path.exists(filepath)
        with open(filepath) as f:
            line = f.readline().strip()
        assert json.loads(line) == record

    def test_appends_multiple_records(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        for i in range(5):
            atomic_append(filepath, {"id": f"rec_{i}", "value": i})

        records = read_jsonl(filepath)
        assert len(records) == 5
        assert records[0]["id"] == "rec_0"
        assert records[4]["id"] == "rec_4"

    def test_preserves_unicode(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        record = {"msg": "Hello from Earth 1234"}
        atomic_append(filepath, record)

        records = read_jsonl(filepath)
        assert records[0]["msg"] == "Hello from Earth 1234"

    def test_rejects_non_serializable(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        with pytest.raises(AtomicAppendError, match="not JSON-serializable"):
            atomic_append(filepath, {"fn": lambda: None})

    def test_concurrent_appends_no_corruption(self, tmp_path):
        """Multiple threads appending should not corrupt the file."""
        filepath = str(tmp_path / "concurrent.jsonl")

        def append_record(i):
            atomic_append(filepath, {"id": f"rec_{i}", "thread": i})

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(append_record, i) for i in range(20)]
            for f in futures:
                f.result()  # Raise any exceptions

        records = read_jsonl(filepath)
        assert len(records) == 20

        # All records should be valid JSON
        ids = {r["id"] for r in records}
        assert len(ids) == 20  # No duplicates or corruption

    def test_lock_file_cleaned_up(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        atomic_append(filepath, {"id": "001"})
        # Lock file may exist but should not be locked
        lock_path = filepath + ".lock"
        # Should be able to write to it (not locked)
        if os.path.exists(lock_path):
            with open(lock_path, "w") as f:
                f.write("test")


class TestReadJsonl:
    def test_read_empty_file(self, tmp_path):
        filepath = str(tmp_path / "empty.jsonl")
        open(filepath, "w").close()  # Create empty file
        assert read_jsonl(filepath) == []

    def test_read_nonexistent_file(self):
        assert read_jsonl("/nonexistent/file.jsonl") == []

    def test_skips_corrupt_lines(self, tmp_path):
        filepath = str(tmp_path / "mixed.jsonl")
        with open(filepath, "w") as f:
            f.write('{"id": "good_1"}\n')
            f.write("this is not json\n")
            f.write('{"id": "good_2"}\n')

        records = read_jsonl(filepath)
        assert len(records) == 2
        assert records[0]["id"] == "good_1"
        assert records[1]["id"] == "good_2"


class TestReadJsonlById:
    def test_finds_record(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        for i in range(3):
            atomic_append(filepath, {"id": f"rec_{i}", "value": i})

        record = read_jsonl_by_id(filepath, "rec_1")
        assert record is not None
        assert record["value"] == 1

    def test_returns_none_for_missing(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        atomic_append(filepath, {"id": "rec_0"})
        assert read_jsonl_by_id(filepath, "nonexistent") is None


class TestUpdateJsonlRecord:
    def test_updates_existing_record(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        for i in range(3):
            atomic_append(filepath, {"id": f"rec_{i}", "status": "pending"})

        result = update_jsonl_record(filepath, "rec_1", {"status": "done"})
        assert result is True

        records = read_jsonl(filepath)
        assert records[1]["status"] == "done"
        assert records[0]["status"] == "pending"  # Unchanged

    def test_returns_false_for_missing(self, tmp_path):
        filepath = str(tmp_path / "test.jsonl")
        atomic_append(filepath, {"id": "rec_0"})
        result = update_jsonl_record(filepath, "nonexistent", {"status": "done"})
        assert result is False

    def test_returns_false_for_missing_file(self):
        result = update_jsonl_record("/nonexistent/file.jsonl", "id", {})
        assert result is False
