from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parent
SRC = BACKEND_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orbit.api.server import run_server


if __name__ == "__main__":
    run_server()
