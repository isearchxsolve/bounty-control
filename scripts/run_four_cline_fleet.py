"""Dispatch cloud workers; never run bounty compute on the laptop."""
import sys
from actions_dispatch import main

if __name__ == "__main__":
    main(["--live", "--max-dispatches", "4", *sys.argv[1:]])
