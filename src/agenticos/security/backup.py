"""Consistent SQLite backup and restore helpers."""

import os
import sqlite3
import tempfile
from pathlib import Path


def _copy_sqlite_database(source: Path | str, destination: Path | str) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)

    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("SQLite source must be an existing regular file")
    if destination_path.is_symlink():
        raise ValueError("SQLite destination must not be a symbolic link")
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("SQLite source and destination must be different")

    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".tmp",
        dir=destination_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        with sqlite3.connect(source_path, timeout=30.0) as source_connection:
            source_check = source_connection.execute("PRAGMA integrity_check").fetchone()
            if source_check is None or source_check[0] != "ok":
                raise sqlite3.DatabaseError("SQLite source failed integrity_check")
            with sqlite3.connect(temporary_path, timeout=30.0) as destination_connection:
                source_connection.backup(destination_connection)
                destination_check = destination_connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                if destination_check is None or destination_check[0] != "ok":
                    raise sqlite3.DatabaseError(
                        "SQLite copy failed integrity_check"
                    )
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, destination_path)
        return destination_path
    finally:
        temporary_path.unlink(missing_ok=True)


def backup_sqlite_database(
    source: Path | str, destination: Path | str
) -> Path:
    """Create a transactionally consistent, integrity-checked SQLite backup."""
    return _copy_sqlite_database(source, destination)


def restore_sqlite_database(
    backup: Path | str, destination: Path | str
) -> Path:
    """Restore a verified SQLite backup atomically into a destination file."""
    return _copy_sqlite_database(backup, destination)
