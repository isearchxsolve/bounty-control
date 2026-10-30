"""Compatibility entrypoint for the shared Actions dispatcher."""
import sys
from actions_dispatch import main

if __name__ == "__main__":
    main(["--lane", "normal", *sys.argv[1:]])
