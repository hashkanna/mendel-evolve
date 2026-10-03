"""Start OpenEvolve's command line with a guard that stops it if the process that started it dies.

Used by run_openevolve.py, in OpenEvolve's own virtual environment:

    vendor/venv/bin/python oe_launch.py <the arguments of openevolve-run.py>

It is `openevolve-run.py` (which only calls `openevolve.cli.main`) plus one thread. Without the
guard, a runner that is killed would leave OpenEvolve running, and spending, with nothing watching
the cap. The guard sends OpenEvolve the signal it already handles for a graceful shutdown, and
kills the process group if that has not finished two minutes later.
"""

import os
import signal
import sys
import threading
import time


def guard(parent: int) -> None:
    while os.getppid() == parent:
        time.sleep(3.0)
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(120.0)
    os.killpg(os.getpgid(0), signal.SIGKILL)


if __name__ == "__main__":
    threading.Thread(target=guard, args=(os.getppid(),), daemon=True).start()
    from openevolve.cli import main

    sys.exit(main())
