"""Move oversized Radar source gzip files through Git without changing their bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


PART_BYTES = 64 * 1024 * 1024
GIT_FILE_LIMIT = 100 * 1024 * 1024
BLOCK_BYTES = 1024 * 1024
SOURCE_NAME = "source.json.gz"


def part_name(index):
    return f"{SOURCE_NAME}.part-{index:04d}"


def write_parts(source, directory):
    parts = []
    with source.open("rb") as incoming:
        while block := incoming.read(BLOCK_BYTES):
            name = part_name(len(parts))
            remaining = PART_BYTES
            digest = hashlib.sha256()
            size = 0
            with (directory / name).open("wb") as outgoing:
                while block:
                    outgoing.write(block)
                    digest.update(block)
                    size += len(block)
                    remaining -= len(block)
                    if not remaining:
                        break
                    block = incoming.read(min(BLOCK_BYTES, remaining))
            parts.append({"name": name, "bytes": size, "sha256": digest.hexdigest()})
    return parts


def source_pieces(report):
    if "source_parts" not in report:
        return [{"name": SOURCE_NAME, "bytes": report["source_bytes"],
                 "sha256": report["source_sha256"]}]
    parts = report["source_parts"]
    if not isinstance(parts, list) or not parts:
        raise ValueError("Missing Radar source parts")
    for index, part in enumerate(parts):
        size = part["bytes"]
        if part["name"] != part_name(index) or type(size) is not int or not 0 < size <= PART_BYTES:
            raise ValueError("Invalid Radar source part")
    return parts


def stage_source(directory, report):
    source = directory / SOURCE_NAME
    if source.stat().st_size != report["source_bytes"]:
        raise ValueError("Staged Radar source size differs from the publication manifest")
    if report["source_bytes"] <= GIT_FILE_LIMIT:
        return [SOURCE_NAME]
    report["source_parts"] = write_parts(source, directory)
    return [part["name"] for part in report["source_parts"]]


def assemble_source(report, open_piece, destination):
    combined = hashlib.sha256()
    total = 0
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staging:
        temporary = Path(staging.name)
        try:
            for part in source_pieces(report):
                digest = hashlib.sha256()
                size = 0
                with open_piece(part["name"]) as incoming:
                    while block := incoming.read(BLOCK_BYTES):
                        size += len(block)
                        if size > part["bytes"]:
                            raise ValueError("Radar source part exceeds its declared size")
                        digest.update(block)
                        combined.update(block)
                        staging.write(block)
                if size != part["bytes"] or digest.hexdigest() != part["sha256"]:
                    raise ValueError(f"Radar source integrity failure for {part['name']}")
                total += size
            if total != report["source_bytes"] or combined.hexdigest() != report["source_sha256"]:
                raise ValueError("Assembled Radar source integrity failure")
            staging.close()
            os.replace(temporary, destination)
        finally:
            staging.close()
            temporary.unlink(missing_ok=True)


def materialize(directory):
    report = json.loads((directory / "publication.json").read_text(encoding="utf-8"))
    if "source_parts" in report:
        assemble_source(report, lambda name: (directory / name).open("rb"), directory / SOURCE_NAME)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    materialize(parser.parse_args().directory)
