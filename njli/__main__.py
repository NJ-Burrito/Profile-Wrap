"""``python -m njli`` entry. Checks the Python version before importing anything else."""
import sys


def _run():
    from njli.bootstrap import find_python

    message = find_python.version_message()
    if message:
        sys.stderr.write(message + "\n")
        return 1
    from njli.cli import main

    return main()


if __name__ == "__main__":
    sys.exit(_run())
