"""Source identity shared by the financial engine and isolated broker runtime."""

import hashlib
from pathlib import Path


def engine_digest() -> str:
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def research_engine_digest() -> str:
    """新研究单独标识金融行为；原账户的完整源码指纹算法保持原样。"""
    display = {
        "cli.py",
        "legacy_cli.py",
        "__main__.py",
        "quant_report.py",
        "report.py",
        "research_report.py",
    }
    digest = hashlib.sha256(b"invest.research.financial.v1\n")
    for source in sorted(Path(__file__).parent.glob("*.py")):
        if source.name not in display:
            digest.update(source.name.encode())
            digest.update(source.read_bytes())
    return digest.hexdigest()
