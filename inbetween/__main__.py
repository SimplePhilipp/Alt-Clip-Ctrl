"""Keep python -m inbetween working after the Alt Clip Ctrl rename."""
from altclipctrl.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
