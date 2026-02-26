#!/bin/env python

# pylint: disable=broad-exception-caught,invalid-name, line-too-long, bare-except
import sys
import os
import subprocess

if __name__ == "__main__":
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    subprocess.run(
        [
            "chown",
            "-R",
            f"{os.environ["SUDO_USER"]}:{os.environ["SUDO_USER"]}",
            ".",
        ],
        check=True,
    )
    subprocess.run(["chmod", "-R", "777", "."], check=True)

    command = os.path.join(os.path.dirname(__file__), "main.py")
    os.execvp("sudo", ["sudo", "-u", os.environ["SUDO_USER"], command] + sys.argv)
