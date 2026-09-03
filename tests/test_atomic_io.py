"""Tests for utils/atomic_io — atomic file write utilities."""
import os, json, tempfile
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from utils.atomic_io import atomic_write_json, atomic_write_pickle


class TestAtomicWriteJson:
    def test_write_and_read(self):
        """写 JSON 再读回 → 内容一致"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.json")
            data = {"a": 1, "b": [2, 3], "c": {"d": "e"}}
            atomic_write_json(path, data)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded == data

    def test_no_partial_file_on_crash(self):
        """写入异常 → temp 文件被清理，旧内容保留"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.json")
            atomic_write_json(path, {"old": "data"})
            # 给一个不可写的路径
            os.chmod(tmp, 0o444)  # read-only dir
            with pytest.raises((PermissionError, OSError)):
                atomic_write_json(path, {"bad": "stuff"})
            os.chmod(tmp, 0o755)  # restore
            # 旧文件保留
            with open(path) as f:
                assert json.load(f) == {"old": "data"}
            # 检查没有残留 .tmp 文件
            leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
            assert len(leftovers) == 0, f"Leftover tmp files: {leftovers}"

    def test_overwrite(self):
        """覆盖已有文件 → 新内容生效"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.json")
            atomic_write_json(path, {"v1": 1})
            atomic_write_json(path, {"v2": 2})
            with open(path) as f:
                assert json.load(f) == {"v2": 2}

    def test_empty_dict(self):
        """空 dict"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.json")
            atomic_write_json(path, {})
            with open(path) as f:
                assert json.load(f) == {}

    def test_list_root(self):
        """根级 list"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "list.json")
            data = [{"a": 1}, {"a": 2}]
            atomic_write_json(path, data)
            with open(path) as f:
                assert json.load(f) == data


class TestAtomicWritePickle:
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pkl")
            data = {"df": [1, 2, 3], "meta": {"count": 3}}
            atomic_write_pickle(path, data)
            import pickle
            with open(path, "rb") as f:
                loaded = pickle.load(f)
            assert loaded == data

    def test_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pkl")
            atomic_write_pickle(path, {"v1": 1})
            atomic_write_pickle(path, {"v2": 2})
            import pickle
            with open(path, "rb") as f:
                assert pickle.load(f) == {"v2": 2}
