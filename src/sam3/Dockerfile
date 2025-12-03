# SAM3 with ROS2 Humble環境用のDockerfile
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04


# 環境変数の設定
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV ROS_DISTRO=humble
ENV PYTHONUNBUFFERED=1

# 基本パッケージのインストール
RUN apt-get update && apt-get install -y \
    software-properties-common \
    curl \
    wget \
    git \
    vim \
    build-essential \
    locales \
    lsb-release \
    gnupg2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ロケール設定
RUN locale-gen en_US.UTF-8

# ROS2 Humbleのインストール
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null

RUN apt-get update && apt-get install -y \
    ros-${ROS_DISTRO}-desktop \
    ros-${ROS_DISTRO}-cv-bridge \
    ros-${ROS_DISTRO}-image-transport \
    ros-${ROS_DISTRO}-vision-msgs \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool \
    && rm -rf /var/lib/apt/lists/*

# rosdepの初期化
RUN rosdep init || true && rosdep update

# pipをアップグレード (System Python 3.10を使用、ROS2と互換性あり)
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3 && \
    python3 -m pip install --upgrade pip setuptools wheel

# 作業ディレクトリの作成
WORKDIR /workspace/sam3

# 依存関係ファイルのコピー
COPY pyproject.toml ./
COPY MANIFEST.in ./
COPY ./markdown/README.md ./
COPY LICENSE ./

# SAM3のディレクトリ構造をコピー
COPY sam3/ ./sam3/

# PyTorchのバージョンとIndex URLを引数で指定可能にする
ARG PYTORCH_VERSION=2.9.0
#バージョン12.6
ARG CUDA_VERSION=126
ARG PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu${CUDA_VERSION}

# PyTorchとCUDAのインストール
# ROS2から既にインストールされているsympyとmpmpathを削除
# torchvision, torchaudioはtorchのバージョンに合わせて依存解決させる
RUN if [ "${PYTORCH_VERSION}" = "latest" ]; then \
    pip install --pre --ignore-installed torch torchvision torchaudio --index-url ${PYTORCH_INDEX_URL}; \
    else \
    pip install --ignore-installed torch==${PYTORCH_VERSION} torchvision torchaudio ;\
    fi

# SAM3とその依存関係のインストール
RUN pip install -e .

# Notebooksとdev用の追加依存関係のインストール（オプション）
RUN pip install -e ".[notebooks,dev]"

# ROS2のセットアップスクリプトを.bashrcに追加
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc

# Hugging Face CLIのインストール
RUN pip install huggingface_hub

# 作業ディレクトリを維持
WORKDIR /workspace/sam3

# エントリーポイントの設定
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
RUN echo "export PS1='\[\e[1;36m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '" >> /root/.bashrc

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["/bin/bash"]
