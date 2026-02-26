#!/bin/env python

# pylint: disable=broad-exception-caught,invalid-name, line-too-long, bare-except

import calendar
from datetime import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request


def __check_version(kernel):
    print("  Checking versions...")

    with urllib.request.urlopen(
        f"https://aur.archlinux.org/rpc/?v=5&type=info&arg={kernel}"
    ) as response:
        try:
            data = response.read()
            text = data.decode("utf-8")
            result = json.loads(text)
            original_version = result["results"][0]["Version"]
            original_updated = result["results"][0]["LastModified"]
            print(
                f"    - Original: {original_version} ({datetime.fromtimestamp(original_updated).strftime("%a %b %d %H:%M:%S %Y")})"
            )
        except:
            pass

    proceed = False
    if "--force" not in sys.argv:
        try:
            native_version = original_version
            native_updated = original_updated

            result = subprocess.run(
                ["pacman", "-Qi", kernel + "-native"],
                check=True,
                capture_output=True,
                env={"LANG": "C"},
            ).stdout.decode()
            for line in result.splitlines():
                if line.startswith("Version"):
                    native_version = line.split(":")[1].strip()
                if line.startswith("Build Date"):
                    dt = datetime.strptime(
                        ":".join(line.split(":")[1:]).strip(), "%a %b %d %H:%M:%S %Y"
                    )
                    native_updated = calendar.timegm(dt.timetuple())
            print(
                f"    - Native:   {native_version} ({datetime.fromtimestamp(native_updated).strftime("%a %b %d %H:%M:%S %Y")})"
            )

            if native_version != original_version or native_updated < original_updated:
                print("  Update available")
                proceed = True

        except:
            print("  Native version not found")
            proceed = True

        if not proceed:
            print("  Kernel up to date")
    else:
        print("    Build and update forced")
        proceed = True

    return (proceed, original_version)


def __get_kernels_to_update():
    kernels = []
    result = {}

    print("Getting kernels to update/install")
    if len(sys.argv) == 1 or "--all" in sys.argv:
        entries = subprocess.run(
            "pacman -Q | grep linux-cachyos | grep headers | grep native",
            shell=True,
            text=True,
            check=False,
            capture_output=True,
        ).stdout.splitlines()
        for entry in entries:
            if "-lts-" in entry:
                continue

            kernels.append(
                entry.split(" ")[0].replace("-headers", "").replace("-native", "")
            )
    else:
        for arg in sys.argv[1:]:
            if not arg.startswith("--"):
                kernels.append(arg)

    for kernel in kernels:
        proceed, VERSION = __check_version(kernel)
        if proceed:
            result[kernel] = VERSION

    if not result:
        print("No kernels to update/install")
        sys.exit(1)

    print(f"  Kernels to update/install: {", ".join(result)}")

    return result


def __download_spec_files(workspace, kernels):
    print("Downloading spec files...")
    for kernel in kernels:
        tgz_path = os.path.join(workspace, f"{kernel}.tar.gz")
        urllib.request.urlretrieve(
            f"https://aur.archlinux.org/cgit/aur.git/snapshot/{kernel}.tar.gz", tgz_path
        )
        subprocess.run(["tar", "-xzf", tgz_path, "-C", workspace], check=True)
        subprocess.run(["rm", "-rf", tgz_path], check=True)


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


def __edit_srcinfo_file(srcinfo):
    print("  Updating .SRCINFO file...")
    subprocess.run(
        f"sudo -u {os.environ["SUDO_USER"]} makepkg --printsrcinfo > {srcinfo}",
        shell=True,
        check=True,
    )


def __edit_pkgbuild_file(new_kernel, pkgbuild):
    print("  Editing PKGBUILD file...")
    with open(pkgbuild, "r", encoding="utf-8") as f:
        pkgbuild_content = f.read()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pkgbuild_content = f"# Updated by Emilio Pulido <ojosdeserbio@gmail.com> on {now}\n\n{pkgbuild_content}"
    pkgbuild_content = pkgbuild_content.replace(
        'pkgbase="linux-$_pkgsuffix"', f'pkgbase="{new_kernel}"'
    )

    KERNEL_PARAMETERS = {
        "_cpusched": "bore",
        "_use_llvm_lto": "full",
        "_processor_opt": "native",
        "_use_lto_suffix": "no",
        "_per_gov": "yes",
        "_tcp_bbr3": "yes",
        "_build_nvidia_open": "yes",
    }

    for parameter, value in KERNEL_PARAMETERS.items():
        pkgbuild_content = re.sub(
            rf'"\$\{{{re.escape(parameter)}:=[^}}]*\}}"',
            f'"${{{parameter}:={value}}}"',
            pkgbuild_content,
        )

    with open(pkgbuild, "w", encoding="utf-8") as f:
        f.write(pkgbuild_content)

    subprocess.run(["chmod", "777", "-R", "."], check=True)
    subprocess.run(
        ["sudo", "-u", os.environ["SUDO_USER"], "updpkgsums"],
        check=True,
    )


def __copy_to_version_dir(base_version_dir, kernel, version, files):
    print(f"Versioning kernel {kernel} for v{version}...")
    VERSION_FOLDER = os.path.join(base_version_dir, kernel, version)
    if os.path.isdir(VERSION_FOLDER):
        shutil.rmtree(VERSION_FOLDER)
    os.makedirs(VERSION_FOLDER)
    for file in files:
        shutil.copy2(file, os.path.join(VERSION_FOLDER, os.path.basename(file)))


def __build_packages(workspace, packages):
    print("Building packages...")
    subprocess.run(["chmod", "777", "-R", "."], check=True)
    subprocess.run(
        ["sudo", "-u", os.environ["SUDO_USER"], "makepkg", "-s"],
        check=True,
    )

    files = glob.glob(f"{workspace}/*.pkg.tar.*")
    for f in files:
        shutil.copy(f, packages)


def __handle_kernel(workspace, packages_dir, version_dir, github, kernel, version):
    NEW_KERNEL_NAME = kernel + "-native"
    print(f"Handling {NEW_KERNEL_NAME}")

    LOCAL_WORKSPACE_DIR = os.path.join(workspace, kernel)
    os.chdir(LOCAL_WORKSPACE_DIR)

    SRCINFO_PATH = os.path.join(LOCAL_WORKSPACE_DIR, ".SRCINFO")
    PKGBUILD_PATH = os.path.join(LOCAL_WORKSPACE_DIR, "PKGBUILD")
    CONFIG_PATH = os.path.join(LOCAL_WORKSPACE_DIR, "config")

    __edit_config_file(CONFIG_PATH)
    __edit_pkgbuild_file(NEW_KERNEL_NAME, PKGBUILD_PATH)
    __edit_srcinfo_file(SRCINFO_PATH)

    __copy_to_version_dir(
        version_dir,
        NEW_KERNEL_NAME,
        version,
        (SRCINFO_PATH, PKGBUILD_PATH, CONFIG_PATH),
    )

    __build_packages(LOCAL_WORKSPACE_DIR, packages_dir)

    os.chdir(workspace)
    shutil.rmtree(LOCAL_WORKSPACE_DIR)


def __install_packages(packages):
    print("Installing packages...")
    globs = glob.glob(f"{packages}/*.pkg.tar.*")
    if len(globs) == 0:
        print("  No packages to install")
        return

    cmd = ["pacman", "--noconfirm", "-U"]
    for glb in globs:
        cmd.append(glb)

    subprocess.run(cmd, check=True)


def __setup_workspace():
    workspace = "/tmp/native-cachyos-generator"
    if os.path.isdir(workspace):
        shutil.rmtree(workspace)
    os.mkdir(workspace)

    versions = os.path.abspath(os.path.join(os.path.dirname(__file__), "versions"))
    if not os.path.isdir(versions):
        os.mkdir(versions)

    github = os.environ.get("GITHUB_ACTIONS") == "true"

    packages = os.path.abspath(os.path.join(workspace, "packages"))

    if not github:
        if not os.path.isdir(packages):
            os.mkdir(packages)

    return (workspace, versions, packages, github)


if __name__ == "__main__":
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    KERNELS = __get_kernels_to_update()

    WORKSPACE_DIR, VERSIONS_DIR, PACKAGES_DIR, GITHUB = __setup_workspace()

    __download_spec_files(WORKSPACE_DIR, KERNELS)

    for KERNEL_NAME, VERSION in KERNELS.items():
        __handle_kernel(
            WORKSPACE_DIR,
            PACKAGES_DIR,
            VERSIONS_DIR,
            GITHUB,
            KERNEL_NAME,
            VERSION,
        )

    if not GITHUB:
        __install_packages(PACKAGES_DIR)

    if os.path.isdir(WORKSPACE_DIR):
        shutil.rmtree(WORKSPACE_DIR)
