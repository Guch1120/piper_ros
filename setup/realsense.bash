#!/bin/bash
# -*- coding: utf-8 -*-

set -euo pipefail

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────

ROS_WS="/ros2_ws"
ROS_DISTRO="${ROS_DISTRO:-humble}"

LIBREALSENSE_KEYRING="/etc/apt/keyrings/librealsenseai.gpg"
LIBREALSENSE_LIST="/etc/apt/sources.list.d/librealsense.list"
UBUNTU_CODENAME="$(lsb_release -cs)"

# apt版realsense-rosを使うか
# 0: SDKだけ入れて、src/realsense-rosをcolcon buildする
# 1: ros-humble-realsense2-camera / msgs / description をaptで入れる
INSTALL_APT_REALSENSE_ROS="${INSTALL_APT_REALSENSE_ROS:-1}"

# src/realsense-rosをclone/buildするか
# 0: clone/buildしない
# 1: clone/buildする
BUILD_SOURCE_REALSENSE_ROS="${BUILD_SOURCE_REALSENSE_ROS:-0}"


# ─────────────────────────────────────────────
# 共通関数
# ─────────────────────────────────────────────

log() {
  echo ""
  echo "============================================================"
  echo "$1"
  echo "============================================================"
}

warn() {
  echo ""
  echo "[WARN] $1"
}

die() {
  echo ""
  echo "[ERROR] $1" >&2
  exit 1
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "$1 コマンドが見つかりません。"
  fi
}

safe_source_ros() {
  local setup_file="$1"

  if [ ! -f "$setup_file" ]; then
    die "$setup_file が見つかりません。"
  fi

  # ROS 2 の setup.bash は未定義変数を参照することがあるため、
  # set -u を一時的に無効化して source する。
  set +u
  # shellcheck disable=SC1090
  source "$setup_file"
  set -u
}


# ─────────────────────────────────────────────
# 0. 前提確認
# ─────────────────────────────────────────────

log "前提コマンドを確認します..."

need_cmd curl
need_cmd gpg
need_cmd lsb_release
need_cmd apt-get
need_cmd python3

if [ "$EUID" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "Ubuntu codename : ${UBUNTU_CODENAME}"
echo "ROS_DISTRO      : ${ROS_DISTRO}"
echo "ROS_WS          : ${ROS_WS}"
echo "sudo            : ${SUDO:-なし/root実行}"


# ─────────────────────────────────────────────
# 1. Intel RealSense SDK / librealsense セットアップ
# ─────────────────────────────────────────────

log "Intel RealSense SDK / librealsense のセットアップを開始します..."

echo "aptキーリング用ディレクトリを作成します..."
$SUDO mkdir -p /etc/apt/keyrings

echo "古いlibrealsense apt設定を削除します..."
$SUDO rm -f /etc/apt/sources.list.d/librealsense.list
$SUDO rm -f /etc/apt/sources.list.d/realsense-public.list
$SUDO rm -f /etc/apt/keyrings/librealsense.pgp
$SUDO rm -f /etc/apt/keyrings/librealsense.gpg
$SUDO rm -f /etc/apt/keyrings/librealsenseai.gpg

echo "必要パッケージを確認・インストールします..."
$SUDO apt-get update
$SUDO apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  python3-pip

echo "新しいRealSense PGPキーを取得・登録します..."
curl -fsSL https://librealsense.realsenseai.com/Debian/librealsenseai.asc \
  | gpg --dearmor \
  | $SUDO tee "$LIBREALSENSE_KEYRING" > /dev/null

$SUDO chmod 644 "$LIBREALSENSE_KEYRING"

echo "aptリポジトリリストを追加します..."
echo "deb [signed-by=${LIBREALSENSE_KEYRING}] https://librealsense.realsenseai.com/Debian/apt-repo ${UBUNTU_CODENAME} main" \
  | $SUDO tee "$LIBREALSENSE_LIST" > /dev/null

echo "追加したaptリポジトリ:"
cat "$LIBREALSENSE_LIST"

echo "パッケージリストを更新します..."
$SUDO apt-get update

echo "librealsenseライブラリをインストールします..."
$SUDO apt-get install -y \
  librealsense2-utils \
  librealsense2-dev \
  librealsense2-dbg

echo "pyrealsense2 をインストールします..."
python3 -m pip install --upgrade pip
python3 -m pip install pyrealsense2

echo "librealsense SDK の確認:"
if command -v realsense-viewer >/dev/null 2>&1; then
  echo "[OK] realsense-viewer: $(command -v realsense-viewer)"
else
  die "realsense-viewer が見つかりません。librealsense2-utils のインストールを確認してください。"
fi


# ─────────────────────────────────────────────
# 2. ROS 2 RealSense セットアップ
# ─────────────────────────────────────────────

log "ROS 2 RealSense セットアップを開始します..."

if [ ! -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
  die "/opt/ros/${ROS_DISTRO}/setup.bash が見つかりません。ROS 2 ${ROS_DISTRO} が未セットアップです。"
fi

echo "ROS 2環境を読み込みます..."
safe_source_ros "/opt/ros/${ROS_DISTRO}/setup.bash"

echo "ROS 2依存パッケージをインストールします..."
$SUDO apt-get update

if [ "$INSTALL_APT_REALSENSE_ROS" = "1" ]; then
  echo "apt版 RealSense ROS 2 パッケージをインストールします..."
  $SUDO apt-get install -y \
    "ros-${ROS_DISTRO}-diagnostic-updater" \
    "ros-${ROS_DISTRO}-realsense2-camera" \
    "ros-${ROS_DISTRO}-realsense2-camera-msgs" \
    "ros-${ROS_DISTRO}-realsense2-description"
else
  echo "apt版 RealSense ROS 2 パッケージはインストールしません。"
  $SUDO apt-get install -y \
    "ros-${ROS_DISTRO}-diagnostic-updater"
fi


# ─────────────────────────────────────────────
# 3. 必要なら source版 realsense-ros を clone/build
# ─────────────────────────────────────────────

if [ "$BUILD_SOURCE_REALSENSE_ROS" = "1" ]; then
  log "source版 realsense-ros を clone/build します..."

  mkdir -p "$ROS_WS/src"
  cd "$ROS_WS/src"

  if [ ! -d "realsense-ros" ]; then
    echo "realsense-ros を clone します..."
    git clone https://github.com/IntelRealSense/realsense-ros.git
  else
    echo "realsense-ros は既に存在します。clone をスキップします。"
  fi

  echo "依存関係を rosdep で解決します..."
  cd "$ROS_WS"

  if command -v rosdep >/dev/null 2>&1; then
    if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
      $SUDO rosdep init || true
    fi

    rosdep update
    rosdep install --from-paths src --ignore-src -r -y --rosdistro "$ROS_DISTRO"
  else
    warn "rosdep が見つかりません。必要なら python3-rosdep をインストールしてください。"
  fi

  echo "ワークスペースをビルドします..."
  colcon build --symlink-install

  echo "source版 realsense-ros のビルドが完了しました。"
else
  log "source版 realsense-ros の clone/build はスキップします。"
  echo "apt版を使う場合はこれでOKです。"
fi


# ─────────────────────────────────────────────
# 4. Gazebo model path 補助設定
# ─────────────────────────────────────────────

log "Gazebo model path を確認します..."

BASHRC_LINE='export GAZEBO_MODEL_PATH=/opt/ros/humble/share:${GAZEBO_MODEL_PATH:-}'

if ! grep -qxF "$BASHRC_LINE" /root/.bashrc 2>/dev/null; then
  echo "$BASHRC_LINE" >> /root/.bashrc
  echo "[OK] /root/.bashrc に GAZEBO_MODEL_PATH を追加しました。"
else
  echo "[OK] /root/.bashrc には既に GAZEBO_MODEL_PATH が設定されています。"
fi

export GAZEBO_MODEL_PATH="/opt/ros/${ROS_DISTRO}/share:${GAZEBO_MODEL_PATH:-}"
echo "GAZEBO_MODEL_PATH=${GAZEBO_MODEL_PATH}"


# ─────────────────────────────────────────────
# 5. Python import確認
# ─────────────────────────────────────────────

log "pyrealsense2 の import を確認します..."

python3 - <<'PY'
try:
    import pyrealsense2 as rs
    print("[OK] pyrealsense2 import")
    print("pyrealsense2 module:", rs)
except Exception as e:
    print("[NG] pyrealsense2 import")
    print(e)
    raise
PY


# ─────────────────────────────────────────────
# 6. ROS package確認
# ─────────────────────────────────────────────

log "RealSense ROS 2 パッケージを確認します..."

safe_source_ros "/opt/ros/${ROS_DISTRO}/setup.bash"

for pkg in realsense2_camera realsense2_camera_msgs realsense2_description; do
  if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
    echo "[OK] $pkg -> $(ros2 pkg prefix "$pkg")"
  else
    die "$pkg が見つかりません。setup_all.bash の再現性が崩れています。"
  fi
done


# ─────────────────────────────────────────────
# 7. 完了メッセージ
# ─────────────────────────────────────────────

log "すべてのセットアップが完了しました。"

echo ""
echo "--- SDK単体の確認 ---"
echo "RealSenseカメラを接続してから:"
echo ""
echo "  realsense-viewer"
echo ""

echo "--- ROS 2 apt版を使う場合 ---"
echo ""
echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
echo "  ros2 launch realsense2_camera rs_launch.py"
echo ""

if [ "$BUILD_SOURCE_REALSENSE_ROS" = "1" ]; then
  echo "--- source版を使う場合 ---"
  echo ""
  echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
  echo "  source ${ROS_WS}/install/local_setup.bash"
  echo "  ros2 launch realsense2_camera rs_launch.py"
  echo ""
fi

echo "--- Piper Gazebo を起動する前の確認 ---"
echo ""
echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
echo "  source ${ROS_WS}/install/local_setup.bash"
echo "  ros2 pkg list | grep realsense"
echo ""

echo "--- よく使うRealSense起動例 ---"
echo ""
echo "  ros2 launch realsense2_camera rs_launch.py \\"
echo "    align_depth.enable:=true \\"
echo "    enable_sync:=true \\"
echo "    enable_rgbd:=true"
echo ""

echo "--- Gazebo camera topic確認 ---"
echo ""
echo "  ros2 topic list | grep -E 'camera|depth|points|image'"
echo ""

