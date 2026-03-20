# ベースイメージ: Ubuntu 22.04 + CUDA 12.8.0 (SAM3に合わせて変更)
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04

# タイムゾーン設定（インタラクティブな質問を回避）と日本語環境
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    tzdata \
    terminator \
    locales \
    fonts-noto-cjk \
    && ln -fs /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US:en

# ROS2 humbleのインストール (公式手順 + 必要なツール)
RUN apt-get update && apt-get install -y \
    gnupg \
    curl \
    nano \
    wget \
    git \
    emacs \
    tree \
    cmake \
    lsb-release \
    software-properties-common \
    build-essential \
    git \
    iputils-ping \   
    iproute2 \
    libgl1-mesa-glx \
    dbus-x11 \
    python3-dev \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*
    
RUN add-apt-repository universe \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null \
    && apt-get update \
    && apt-get install -y \
    ros-humble-desktop \
    ros-humble-gazebo-ros-pkgs \
    ros-humble-gazebo-ros2-control \
    ros-humble-ros-gz \
    ros-humble-xacro \
    ros-dev-tools \
    python3-pip \
    can-utils \
    ethtool \
    net-tools \
    ros-humble-cv-bridge \
    ros-humble-image-transport \
    ros-humble-vision-msgs

# piper_ros の依存関係のインストール (README より)
RUN apt-get update && apt-get install -y \
    ros-humble-ros2-control \
    ros-humble-ros2-controllers \
    ros-humble-controller-manager \
    ros-humble-joint-state-publisher-gui \
    ros-humble-robot-state-publisher \
    && rm -rf /var/lib/apt/lists/*

# Python (pip) の依存関係
RUN pip3 install \
    python-can \
    scipy==1.11.4 \
    piper_sdk \
    colcon-common-extensions \
    huggingface_hub

# PyTorch Installation for SAM3 (CUDA 12.8)
# Using PyTorch 2.9.0 with CUDA 12.8 support
RUN pip3 install --pre --ignore-installed torch==2.9.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

#Record3d用インストール
RUN apt-get update && apt-get install -y \
    mpg123 \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install gTTS lzfse opencv-contrib-python

# ワークスペースの作成
RUN mkdir -p /ros2_ws/src
WORKDIR /ros2_ws

# ROS環境のセットアップを　.bashrcに追加
RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc
#ターミナルの色変更
RUN echo "export PS1='\[\e[1;36m\]\u@\h\[\e[0m\]:\[\e[1;34m\]\w\[\e[0m\]\$ '" >> /root/.bashrc
# Gitの所有権エラー回避設定
RUN git config --global --add safe.directory /ros2_ws

# コンテナ起動時のデフォルトコマンド
CMD ["/bin/bash"]