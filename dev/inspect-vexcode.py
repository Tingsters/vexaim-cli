"""Read installed Windows VEXcode AIM source assets; never launch or alter it.

Extracted reference code stays under an ignored local directory. No account,
credential, robot connection, upload or firmware operation is involved.
"""

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path, PurePosixPath


def files(tree, prefix=""):
    for name, entry in tree.items():
        path = prefix + name
        if "files" in entry:
            yield from files(entry["files"], path + "/")
        else:
            yield path, entry


def inspect(archive_path, output):
    archive_path = Path(archive_path).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with archive_path.open("rb") as archive:
        manifest = {
            "archive": str(archive_path),
            "archive_sha256": hashlib.file_digest(archive, "sha256").hexdigest(),
            "assets": [],
        }
        archive.seek(0)
        first, header_size, object_size, json_size = struct.unpack(
            "<IIII", archive.read(16)
        )
        if (
            first != 4
            or not 0 < json_size < 64 * 1024 * 1024
            or not json_size < object_size <= header_size
        ):
            raise ValueError("Unexpected ASAR header")
        tree = json.loads(archive.read(json_size))
        size = archive_path.stat().st_size
        for name, entry in files(tree["files"]):
            if entry.get("unpacked") or entry.get("link"):
                continue
            wanted = name.endswith(".js") and re.search(
                r"AIM|vex-ble-device|vex-serial|Bluetooth|VexSerial",
                name,
                re.IGNORECASE,
            )
            if not wanted and name not in ("package.json", "dist/appversion.txt"):
                continue
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or "\\" in name
                or ":" in name
            ):
                raise ValueError("Unsafe reference asset path")
            offset, count = 8 + header_size + int(entry["offset"]), int(entry["size"])
            if offset < 8 + header_size or count < 0 or offset + count > size:
                raise ValueError("ASAR asset outside archive")
            archive.seek(offset)
            data = archive.read(count)
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            text = data.decode(errors="replace")
            manifest["assets"].append(
                {
                    "path": name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "methods": sorted(set(re.findall(r'key:"([A-Za-z0-9_]+)"', text))),
                }
            )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("C:/Program Files/VEX Robotics/VEXcode AIM/resources/app.asar"),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".vexaim/keepalive/vexcode-reference")
    )
    args = parser.parse_args()
    result = inspect(args.archive, args.output_dir)
    print(
        json.dumps(
            {
                "archive_sha256": result["archive_sha256"],
                "assets": len(result["assets"]),
                "manifest": str((args.output_dir / "manifest.json").resolve()),
            }
        )
    )
