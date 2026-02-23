#!/bin/env python

# pylint: disable=consider-using-dict-items

from urllib import request

import json
import os
import re
import shutil
import subprocess
import sys

cwd = os.getcwd()
print(f"Current working directory {cwd}")
linux_cachyos_dir = os.path.join(cwd, "linux-cachyos")

kernels = {
    "linux-cachyos-bore": {
        "replacements": {
            "_build_nvidia_open": "yes",
            "_use_llvm_lto": "full",
            "_processor_opt": "native",
            "_use_lto_suffix": "no",
        }
    }
}


def __get_kernels():
    result = {}

    original_vers = native_vers = "0.0.0-1"

    for kernel in kernels:
        with request.urlopen(
            f"https://aur.archlinux.org/rpc/?v=5&type=info&arg={kernel}"
        ) as response:
            data = response.read()
            data = json.loads(data.decode("utf-8"))
            original_vers = data["results"][0]["Version"]

        with request.urlopen(
            f"https://aur.archlinux.org/rpc/?v=5&type=info&arg={kernel}-native"
        ) as response:
            data = response.read()
            data = json.loads(data.decode("utf-8"))
            native_vers = data["results"][0]["Version"]

        orig_vers = original_vers.replace(".", " ").replace("-", " ").split(" ")
        aur_vers = native_vers.replace(".", " ").replace("-", " ").split(" ")

        for i in range(len(orig_vers)):
            if int(orig_vers[i]) > int(aur_vers[i]):
                result[kernel] = original_vers
                print(f"{kernel}-native {native_vers} -> {original_vers}")
                break

    return result


def __build_container():
    print("Preparing Docker image...")
    subprocess.run(["docker", "build", "-t", "arch-pkg-ci", "."], check=True)


def __prepare_workspace():
    if os.path.isdir(linux_cachyos_dir):
        print("Deleting Linux CachyOS repository...")
        shutil.rmtree(linux_cachyos_dir)

    print("Cloning Linux CachyOS repository...")
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "https://github.com/CachyOS/linux-cachyos",
            linux_cachyos_dir,
        ],
        check=True,
    )

    subprocess.run(["chmod", "-R", "777", cwd], check=True)


def __handle_kernel(kernel_name: str, version: str):
    kernel_entry = kernels[kernel_name]

    print(f"Handling kernel {kernel_name}...")
    kernel_dir = os.path.join(linux_cachyos_dir, kernel_name)
    os.chdir(kernel_dir)

    print("  Updating PKGBUILD...")
    with open("PKGBUILD", "r", encoding="utf-8") as f:
        pkgbuild_content = f.read()

    pkgbuild_content = pkgbuild_content.replace(
        'pkgbase="linux-$_pkgsuffix"', 'pkgbase="linux-$_pkgsuffix-native"'
    )

    for replacement in kernel_entry["replacements"]:
        pkgbuild_content = re.sub(
            rf'"\$\{{{re.escape(replacement)}:=[^}}]*\}}"',
            f'"${{{replacement}:={kernel_entry["replacements"][replacement]}}}"',
            pkgbuild_content,
        )

    with open("PKGBUILD", "w", encoding="utf-8") as f:
        f.write(pkgbuild_content)

    print("  Generating checksums...")
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.getcwd()}:/repo", "arch-pkg-ci"],
        check=True,
    )

    print("  Updating .SRCINFO...")
    subprocess.run("makepkg --printsrcinfo > .SRCINFO", shell=True, check=True)

    print("  Generating AUR release...")
    subprocess.run(
        [
            "git",
            "clone",
            f"ssh://aur@aur.archlinux.org/{kernel_name}-native.git",
            "aur",
        ],
        check=True,
    )
    shutil.copy(".SRCINFO", os.path.join("aur", ".SRCINFO"))
    shutil.copy("PKGBUILD", os.path.join("aur", "PKGBUILD"))
    shutil.copy("config", os.path.join("aur", "config"))

    os.chdir(os.path.join(kernel_dir, "aur"))
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(
        ["git", "commit", "-m", version],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)


if __name__ == "__main__":
    subprocess.run(["chmod", "-R", "777", cwd], check=True)

    updated_kernels = __get_kernels()
    if len(updated_kernels) == 0:
        print("No kernels to update")
        sys.exit(0)

    __build_container()

    __prepare_workspace()

    for kernel_name in updated_kernels:
        __handle_kernel(kernel_name, updated_kernels[kernel_name])
