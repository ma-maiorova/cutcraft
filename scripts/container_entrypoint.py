"""Initialize the output mount, then run the command without root privileges."""
import os
import sys
from pathlib import Path


def main():
    uid = int(os.environ.get("CUTCRAFT_UID", "1000"))
    gid = int(os.environ.get("CUTCRAFT_GID", "1000"))
    if uid <= 0 or gid <= 0:
        raise ValueError("CUTCRAFT_UID and CUTCRAFT_GID must be positive")
    output = Path('/app/output')
    output.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(output, uid, gid)  # Only the mount root; never recurse into user files.
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    if not os.access(output, os.W_OK):
        raise PermissionError("Output mount is not writable")
    if len(sys.argv) < 2:
        raise ValueError("Missing container command")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    main()
