# ベースイメージ: Ubuntu 20.04 (humbleベース) + CUDA 12.4.1 (devel版)
# 根拠: ぐっちーのCUDA 12.4対応要望とWeb検索結果
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

# タイムゾーン設定（インタラクティブな質問を回避）と日本語環境
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    tzdata \
    locales \
    && ln -fs /usr/share/zoneinfo/Asia/Tokyo /etc/localtime \
    && dpkg-reconfigure --frontend noninteractive tzdata \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG en_US.UTF-8

# ROS2 humbleのインストール (公式手順 + 必要なツール)
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    software-properties-common \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository universe \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/ros2.list > /dev/null \
    && apt-get update \
    && apt-get install -y \
    ros-humble-desktop \
    ros-humble-gazebo-ros-pkgs \
    ros-humble-gazebo-ros2-control \
    ros-humble-xacro \
    ros-dev-tools \
    python3-pip \
    can-utils \
    ethtool \
    net-tools

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
    scipy \
    piper_sdk \
    colcon-common-extensions

# ROS環境のセットアップ
RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc

# ワークスペースの作成
RUN mkdir -p /workspace/ros2_ws/src
WORKDIR /workspace/ros2_ws

# コンテナ起動時のデフォルトコマンド
CMD ["/bin/bash"]