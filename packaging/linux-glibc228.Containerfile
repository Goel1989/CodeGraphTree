# Linux build on glibc 2.28: runs on Ubuntu 20.04+ and RHEL/Rocky 8+.
# Python is built with --enable-shared (PyInstaller requires libpython; manylinux Pythons do not fit).
FROM rockylinux:8
RUN dnf -y install gcc make zlib-devel bzip2-devel xz-devel libffi-devel openssl-devel sqlite-devel \
        readline-devel tar gzip findutils fontconfig libxkbcommon-x11 xcb-util-wm xcb-util-image \
        xcb-util-keysyms xcb-util-renderutil xcb-util-cursor && dnf clean all
ARG PY=3.12.10
RUN curl -fsSL https://www.python.org/ftp/python/${PY}/Python-${PY}.tgz | tar xz -C /tmp \
 && cd /tmp/Python-${PY} && ./configure --enable-shared --enable-optimizations LDFLAGS="-Wl,-rpath,/usr/local/lib" \
 && make -j"$(nproc)" && make install && rm -rf /tmp/Python-${PY}
WORKDIR /src
COPY . /src
RUN python3.12 -m pip install --no-cache-dir -e ".[dev]" pyinstaller
CMD ["python3.12", "tools/build_portable.py"]
