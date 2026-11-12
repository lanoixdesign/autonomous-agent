"""PyInstaller entry point for the desktop builds (double-click)."""
from agent.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
