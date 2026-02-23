FROM archlinux:latest

# Inicializar keyring correctamente
RUN pacman-key --init \
    && pacman-key --populate archlinux \
    && pacman -Sy --noconfirm archlinux-keyring

# Actualizar sistema e instalar dependencias necesarias
RUN pacman -Syu --noconfirm \
    base-devel \
    git \
    pacman-contrib \
    sudo \
    && pacman -Scc --noconfirm

# Crear usuario no-root
RUN useradd -m -s /bin/bash builder \
    && echo "builder ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Establecer directorio de trabajo
WORKDIR /repo

# Cambiar a usuario no-root
USER builder

# Por defecto abre bash
CMD ["updpkgsums"]