#!/bin/env python

# pylint: disable=consider-using-dict-items, redefined-outer-name, line-too-long, consider-using-enumerate


from urllib import request
from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import hashlib

CWD = os.getcwd()
print(f"Current working directory {CWD}")
WORKSPACE = os.path.join(CWD, "workspace")

with open(os.path.join(CWD, "config.json"), "r", encoding="utf-8") as f:
    KERNELS_CONFIG: dict[str, dict[str, str]] = json.load(f)


def __get_kernels():
    print("Checking kernels to update...")
    result = {}

    force = "--force" in sys.argv
    original_vers = native_vers = "0.0.0-1"
    original_pkgvers = native_pkgvers = "0.0.0"
    original_pkgrel = native_pkgrel = "1"

    for kernel in KERNELS_CONFIG:
        print(f"  Looking for {kernel} updates...")
        with request.urlopen(
            f"https://aur.archlinux.org/rpc/?v=5&type=info&arg={kernel}"
        ) as response:
            data = response.read()
            data = json.loads(data.decode("utf-8"))
            original_vers = data["results"][0]["Version"]
            original_upd = data["results"][0]["LastModified"]
            original_pkgvers, original_pkgrel = original_vers.split("-")
            print(
                f"      - Original: {original_vers} ({datetime.fromtimestamp(original_upd).strftime("%a %b %d %H:%M:%S %Y")})"
            )

        with request.urlopen(
            f"https://aur.archlinux.org/rpc/?v=5&type=info&arg={kernel}-native"
        ) as response:
            data = response.read()
            data = json.loads(data.decode("utf-8"))
            if len(data["results"]) == 0:
                print("      - Native package not available")
            else:
                native_vers = data["results"][0]["Version"]
                native_upd = data["results"][0]["LastModified"]
                native_pkgvers, native_pkgrel = native_vers.split("-")
                print(
                    f"      - Native:   {native_vers} ({datetime.fromtimestamp(native_upd).strftime("%a %b %d %H:%M:%S %Y")})"
                )

        if KERNELS_CONFIG[kernel]["check_src"]:
            print("    Checking source files...")
            changed_deps = False
            with request.urlopen(
                f"https://aur.archlinux.org/cgit/aur.git/plain/.SRCINFO?h={kernel}-native"
            ) as response:
                sources = []
                b2sums = []
                skipped = []

                data = response.read().decode("utf-8").splitlines()
                idx = 0
                for line in data:
                    line = line.strip()
                    if line.startswith("source = "):
                        if line.endswith(".tar.xz") or line.endswith(".tar.gz"):
                            skipped.append(idx)
                        else:
                            sources.append(line.split(" = ")[1])
                        idx = idx + 1

                idx = 0
                for line in data:
                    line = line.strip()
                    if line.startswith("b2sums = "):
                        if idx in skipped:
                            skipped.append(idx)
                        else:
                            b2sums.append(line.split(" = ")[1])
                        idx = idx + 1

            for i in range(len(sources)):
                url = (
                    sources[i]
                    if sources[i].startswith("https://")
                    else f"https://aur.archlinux.org/cgit/aur.git/plain/{sources[i]}?h={kernel}-native"
                )

                h = hashlib.blake2b()  # equivalente a b2sum
                with request.urlopen(url) as response:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        h.update(chunk)
                calculated = h.hexdigest()
                if calculated != b2sums[i]:
                    print("      Source files changed")
                    changed_deps = True
                    break

        if original_pkgvers != native_pkgvers:
            print(f"    Update available -> {original_vers}")
            result[kernel] = original_vers
        elif float(original_pkgrel) > float(native_pkgrel):
            print(f"    Update available -> {original_vers}")
            result[kernel] = original_vers
        elif changed_deps or native_upd < original_upd or force:
            pkgrel = native_vers.split("-")[1]
            if "." in pkgrel:
                [major, minor] = pkgrel.split(".")
                minor = str(int(minor) + 1)
                pkgrel = f"{major}.{minor}"
            else:
                pkgrel = pkgrel + ".1"
            vers = native_vers.split("-")[0] + "-" + pkgrel
            if force:
                print(f"    Update forced -> {vers}")
            else:
                print(f"    Update available -> {vers}")
            result[kernel] = vers
        else:
            print("    Up to date")

    return result


def __prepare_workspace(updated_kernel):
    if os.path.isdir(WORKSPACE):
        print("Deleting Workspace...")
        shutil.rmtree(WORKSPACE)
    os.mkdir(WORKSPACE)

    print("Downloading spec files...")
    for kernel in updated_kernel:
        tgz_path = os.path.join(WORKSPACE, f"{kernel}.tar.gz")
        request.urlretrieve(
            f"https://aur.archlinux.org/cgit/aur.git/snapshot/{kernel}.tar.gz", tgz_path
        )
        subprocess.run(["tar", "-xzf", tgz_path, "-C", WORKSPACE], check=True)
        subprocess.run(["rm", "-rf", tgz_path], check=True)

    subprocess.run(["chmod", "-R", "777", WORKSPACE], check=True)


def __build_containers():
    print("Preparing Docker images...")
    subprocess.run(
        ["docker", "build", "--target", "srcinfo", "-t", "arch-srcinfo", "."],
        check=True,
    )
    subprocess.run(
        ["docker", "build", "--target", "sums", "-t", "arch-sums", "."], check=True
    )


def __edit_config_file(config):
    print("  Editing config file...")
    with open(config, "r", encoding="utf-8") as f:
        config_content = f.read()

    config_lines = config_content.splitlines()
    for i, line in enumerate(config_lines):
        if line.startswith("CONFIG_MITIGATION_") or line.startswith(
            "CONFIG_CPU_MITIGATIONS"
        ):
            config_lines[i] = line.split("=")[0] + "=n"

    config_lines.append("CONFIG_ADDRESS_MASKING=n")
    with open(config, "w", encoding="utf-8") as f:
        f.write("\n".join(config_lines))


def __edit_pkgbuild_file(kernel_name, version, new_kernel, pkgbuild):
    print("  Editing PKGBUILD file...")
    with open(pkgbuild, "r", encoding="utf-8") as f:
        pkgbuild_content = f.read()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pkgbuild_content = f"# Updated by Emilio Pulido <ojosdeserbio@gmail.com> on {now}\n\n{pkgbuild_content}"
    pkgbuild_content = pkgbuild_content.replace(
        'pkgbase="linux-$_pkgsuffix"', f'pkgbase="{new_kernel}"'
    )

    for parameter, value in KERNELS_CONFIG[kernel_name]["properties"].items():
        pkgbuild_content = re.sub(
            rf'"\$\{{{re.escape(parameter)}:=[^}}]*\}}"',
            f'"${{{parameter}:={value}}}"',
            pkgbuild_content,
        )

    major = ".".join(version.split(".")[0:2])
    minor = version.split(".")[2].split("-")[0]
    pkgrel = ".".join(version.split(".")[2:]).split("-")[1]

    print(f"{major} {minor} {pkgrel}")
    pkgbuild_lines = pkgbuild_content.splitlines()
    for i in range(len(pkgbuild_lines)):
        if pkgbuild_lines[i].startswith("_major"):
            pkgbuild_lines[i] = f"_major={major}"
        elif pkgbuild_lines[i].startswith("_minor"):
            pkgbuild_lines[i] = f"_minor={minor}"
        elif pkgbuild_lines[i].startswith("pkgrel"):
            pkgbuild_lines[i] = f"pkgrel={pkgrel}"

    pkgbuild_content = "\n".join(pkgbuild_lines)
    with open(pkgbuild, "w", encoding="utf-8") as f:
        f.write(pkgbuild_content)

    print("    Generating checksums...")
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.getcwd()}:/repo", "arch-sums"],
        check=True,
    )


def __edit_srcinfo_file():
    print("  Updating .SRCINFO file...")
    subprocess.run(
        ["docker", "run", "--rm", "-v", f"{os.getcwd()}:/repo", "arch-srcinfo"],
        check=True,
    )


def __generate_aur_release(kernel_name, version):
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

    prev_cwd = os.getcwd()
    os.chdir(os.path.join(os.getcwd(), "aur"))
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(
        ["git", "commit", "-m", version],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)
    os.chdir(prev_cwd)


def __handle_kernel(kernel_name: str, version: str):

    print(f"Handling kernel {kernel_name} v{version}...")
    kernel_dir = os.path.join(WORKSPACE, kernel_name)
    os.chdir(kernel_dir)

    __edit_config_file(os.path.join(kernel_dir, "config"))
    __edit_pkgbuild_file(
        kernel_name,
        version,
        f"{kernel_name}-native",
        os.path.join(kernel_dir, "PKGBUILD"),
    )
    __edit_srcinfo_file()

    __generate_aur_release(kernel_name, version)


if __name__ == "__main__":
    subprocess.run(["chmod", "-R", "777", CWD], check=True)

    updated_kernels = __get_kernels()

    if len(updated_kernels) == 0:
        print("No kernels to update")
        sys.exit(0)

    __build_containers()

    __prepare_workspace(updated_kernels)

    for kernel_name in updated_kernels:
        __handle_kernel(kernel_name, updated_kernels[kernel_name])
