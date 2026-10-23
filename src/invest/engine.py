"""Source identity shared by the financial engine and isolated broker runtime."""

import hashlib
from pathlib import Path


def engine_digest() -> str:
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()
