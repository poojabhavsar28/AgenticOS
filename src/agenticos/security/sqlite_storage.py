"""Private filesystem handling for SQLite-backed security and runtime state."""

import os
import stat
from pathlib import Path


def prepare_private_sqlite_database(database_path: Path | str) -> Path:
    """Create a SQLite file under a private, owner-controlled directory."""
    path = Path(database_path)
    parent = path.parent
    parent_was_missing = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    if parent.is_symlink():
        raise PermissionError("SQLite data directory must not be a symbolic link")

    if os.name == "nt":
        # chmod is best-effort on Windows; operators must apply the documented
        # restrictive NTFS ACL to the directory and its inherited children.
        try:
            parent.chmod(0o700)
        except OSError as exc:
            raise PermissionError("Could not restrict SQLite data directory") from exc
    else:
        directory_stat = parent.stat()
        if directory_stat.st_uid != os.getuid():
            raise PermissionError("SQLite data directory must be owned by the service user")
        directory_mode = stat.S_IMODE(directory_stat.st_mode)
        if directory_mode & 0o077:
            if parent_was_missing or parent.name == ".agenticos":
                parent.chmod(0o700)
            else:
                raise PermissionError(
                    "SQLite data directory is accessible by group/other users; "
                    "use a dedicated private directory"
                )

    if path.is_symlink():
        raise PermissionError("SQLite database must not be a symbolic link")

    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise PermissionError("SQLite database path must be a regular file")
        if os.name != "nt" and file_stat.st_uid != os.getuid():
            raise PermissionError("SQLite database must be owned by the service user")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            os.chmod(path, 0o600)
    finally:
        os.close(descriptor)

    harden_sqlite_files(path)
    return path


def harden_sqlite_files(database_path: Path | str) -> None:
    """Restrict the database and any SQLite rollback/WAL sidecar files."""
    path = Path(database_path)
    for candidate in (
        path,
        Path(f"{path}-journal"),
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
    ):
        try:
            if candidate.is_symlink():
                raise PermissionError("SQLite database and sidecars must not be symbolic links")
            if candidate.exists():
                candidate.chmod(0o600)
        except OSError as exc:
            raise PermissionError(f"Could not restrict SQLite file: {candidate.name}") from exc
