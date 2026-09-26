"""File manager: per-project workspace folders, naming convention and safe path access."""
from __future__ import annotations

import hashlib
import re
import shutil
from datetime import date
from pathlib import Path

from app.core.config import get_settings

WORKSPACE_FOLDERS = ("research", "documents", "presentations", "spreadsheets", "source_files", "final", "archive", "data")

FOLDER_FOR_FORMAT = {
    "docx": "documents", "pdf": "documents", "md": "documents", "txt": "documents",
    "pptx": "presentations",
    "xlsx": "spreadsheets", "csv": "spreadsheets",
    "json": "research",
}


class UnsafePathError(ValueError):
    pass


def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    text = re.sub(r"[\s-]+", "_", text)
    return text[:max_len].strip("_") or "untitled"


def project_root(project_slug: str | None) -> Path:
    root = get_settings().workspace_dir / (slugify(project_slug) if project_slug else "_inbox")
    for folder in WORKSPACE_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


def versioned_filename(title: str, version: int | str, ext: str, on: date | None = None) -> str:
    label = version if isinstance(version, str) else f"v{version}"
    return f"{(on or date.today()).isoformat()}_{slugify(title)}_{label}.{ext.lstrip('.')}"


def artifact_path(project_slug: str | None, title: str, version: int | str, ext: str) -> Path:
    folder = FOLDER_FOR_FORMAT.get(ext.lstrip("."), "documents")
    path = project_root(project_slug) / folder / versioned_filename(title, version, ext)
    if path.exists():  # never overwrite: bump a suffix
        stem, n = path.stem, 2
        while path.exists():
            path = path.with_name(f"{stem}-{n}{path.suffix}")
            n += 1
    return path


def promote_to_final(src: Path, project_slug: str | None) -> Path:
    dest = project_root(project_slug) / "final" / re.sub(r"_v\d+(-\d+)?\.", "_final.", src.name)
    if dest.exists():
        archive = project_root(project_slug) / "archive" / f"{dest.stem}_{hashlib.md5(dest.read_bytes()).hexdigest()[:6]}{dest.suffix}"
        shutil.move(dest, archive)
    shutil.copy2(src, dest)
    return dest


def safe_resolve(path: str | Path) -> Path:
    """Resolve a path and refuse anything outside the workspace (file access control)."""
    root = get_settings().workspace_dir.resolve()
    p = Path(path)
    resolved = (p if p.is_absolute() else root / p).resolve()
    if resolved != root and root not in resolved.parents:
        raise UnsafePathError(f"path outside workspace: {path}")
    return resolved


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()
