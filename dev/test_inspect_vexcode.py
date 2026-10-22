"""Reference inspection must not escape its output directory or archive bounds."""

import importlib.util
import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

spec = importlib.util.spec_from_file_location(
    "vexcode_inspect", Path(__file__).with_name("inspect-vexcode.py")
)
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


class ArchiveTests(unittest.TestCase):
    def archive(self, root, name="AIM.js", offset="0", size=4):
        header = json.dumps(
            {"files": {name: {"size": size, "offset": offset}}}
        ).encode()
        path = root / "app.asar"
        path.write_bytes(
            struct.pack("<IIII", 4, len(header) + 8, len(header) + 4, len(header))
            + header
            + b"test"
        )
        return path

    def test_safe_asset_is_hash_checked_without_changing_archive(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.archive(root)
            before = path.read_bytes()
            result = inspector.inspect(path, root / "references")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((root / "references/AIM.js").read_bytes(), b"test")
            self.assertEqual(result["assets"][0]["bytes"], 4)

    def test_traversal_is_rejected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.archive(root, "../AIM.js")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                inspector.inspect(path, root / "references")
            self.assertFalse((root / "AIM.js").exists())

    def test_corrupt_offset_is_not_read_as_reference_code(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "outside"):
                inspector.inspect(self.archive(root, offset="500"), root / "references")


if __name__ == "__main__":
    unittest.main()
