FROM archlinux:latest AS base

RUN pacman-key --init \
    && pacman-key --populate archlinux \
    && pacman -Sy --noconfirm archlinux-keyring

RUN pacman -Syu --noconfirm \
    base-devel \
    git \
    pacman-contrib \
    sudo \
    && pacman -Scc --noconfirm

RUN useradd -m -s /bin/bash builder \
    && echo "builder ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

WORKDIR /repo
USER builder


FROM base AS srcinfo
CMD ["sh", "-c", "makepkg --printsrcinfo > .SRCINFO"]

FROM base AS sums
CMD ["updpkgsums"]