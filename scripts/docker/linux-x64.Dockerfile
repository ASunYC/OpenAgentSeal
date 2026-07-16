FROM mcr.microsoft.com/mirror/docker/library/ubuntu@sha256:1c4cc37c10c4678fd5369d172a4e079af8a28a6e6f724647ccaa311b4801c3c9 AS builder

ARG NODE_VERSION=20.19.4
ARG UBUNTU_MIRROR=http://mirrors.aliyun.com/ubuntu
ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/root/.cargo/bin:/opt/node/bin:/workspace/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    APPIMAGE_EXTRACT_AND_RUN=1

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && sed -i \
      -e "s|http://archive.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" \
      -e "s|http://security.ubuntu.com/ubuntu|${UBUNTU_MIRROR}|g" \
      /etc/apt/sources.list \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Pipeline-Depth=0 update \
    && apt-get -o Acquire::Retries=5 -o Acquire::http::Pipeline-Depth=0 \
      install -y --fix-missing --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    file \
    git \
    libayatana-appindicator3-dev \
    libfuse2 \
    librsvg2-dev \
    libssl-dev \
    libwebkit2gtk-4.1-dev \
    libxdo-dev \
    patchelf \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    wget \
    xz-utils

RUN curl -fsSLo /tmp/node.tar.xz \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && mkdir -p /opt/node \
    && tar -xJf /tmp/node.tar.xz --strip-components=1 -C /opt/node \
    && rm /tmp/node.tar.xz \
    && node --version \
    && npm --version

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal \
    && rustc --version \
    && cargo --version

WORKDIR /workspace
COPY open_agent/app/web/package.json open_agent/app/web/package-lock.json open_agent/app/web/
COPY desktop/package.json desktop/package-lock.json desktop/

RUN --mount=type=cache,target=/root/.npm \
    npm ci --prefix open_agent/app/web \
    && npm ci --prefix desktop

COPY . .

RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/workspace/.venv,sharing=locked \
    test -x .venv/bin/python || python3 -m venv .venv \
    && .venv/bin/python -m pip install --upgrade pip setuptools wheel \
    && .venv/bin/python -m pip install -e . "pyinstaller>=6.19,<7"

RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/workspace/desktop/src-tauri/target \
    --mount=type=cache,target=/workspace/.venv,sharing=locked \
    --mount=type=cache,target=/workspace/build/pyinstaller,sharing=locked \
    npm --prefix desktop run build \
    && .venv/bin/python scripts/packaging/open_agent_cli.py --version \
    && test -x dist/OpenAgentSeal-linux-x64/cli/portable/openagentseal-cli \
    && dist/OpenAgentSeal-linux-x64/cli/portable/openagentseal-cli --version \
    && test -n "$(find dist/OpenAgentSeal-linux-x64/desktop/installers -name '*.deb' -print -quit)" \
    && test -n "$(find dist/OpenAgentSeal-linux-x64/desktop/installers -name '*.AppImage' -print -quit)" \
    && test -z "$(find dist/OpenAgentSeal-linux-x64 \
      \( -type d -name __pycache__ -o -type f -name '*.py[co]' \) -print -quit)"

RUN set -eu; \
    sidecar=desktop/src-tauri/binaries/open-agent-backend-x86_64-unknown-linux-gnu; \
    mkdir -p /tmp/openagentseal-smoke-workspace; \
    "$sidecar" --web-only --no-browser --host 127.0.0.1 --port 19999 \
      --workspace /tmp/openagentseal-smoke-workspace >/tmp/openagentseal-backend.log 2>&1 & \
    pid=$!; \
    ready=0; \
    for attempt in $(seq 1 40); do \
      if curl -fsS http://127.0.0.1:19999/api/health >/tmp/openagentseal-health.json; then \
        ready=1; \
        break; \
      fi; \
      sleep 0.5; \
    done; \
    if [ "$ready" -ne 1 ]; then \
      cat /tmp/openagentseal-backend.log; \
      kill "$pid" 2>/dev/null || true; \
      exit 1; \
    fi; \
    cat /tmp/openagentseal-health.json; \
    kill "$pid"; \
    wait "$pid" || true

FROM scratch AS export
COPY --from=builder /workspace/dist/OpenAgentSeal-linux-x64/ /
