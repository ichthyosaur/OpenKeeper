from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    backend_dir = os.path.join(exe_dir, "backend")
    if not os.path.isdir(backend_dir):
        backend_dir = os.path.join(exe_dir, "_internal", "backend")
    if not os.path.isdir(backend_dir):
        raise RuntimeError(f"backend directory not found: {backend_dir}")
    os.chdir(exe_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False, app_dir=backend_dir)


if __name__ == "__main__":
    main()
