"""``python -m profile_wrap`` entry. Checks the Python version before importing anything else."""
import sys


def _run():
    from profile_wrap.bootstrap import find_python

    message = find_python.version_message()
    if message:
        sys.stderr.write(message + "\n")
        return 1
    from profile_wrap.cli import main

    return main()


if __name__ == "__main__":
    sys.exit(_run())
