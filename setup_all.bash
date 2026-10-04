#!/bin/bash
# setup_all.sh

# エラーが発生したらそこでスクリプトを止める設定（これ大事だよ）
set -e

pin_python_versions() {
    echo "----------------------------------------"
    echo "Python 数値計算ライブラリのバージョンを固定します..."

    # opencv の最新版は NumPy 2.x を引き込み、SciPy 1.11.4 と壊れた混在状態に
    # なることがあるため、最後に必ず互換セットへ戻す。
    python3 -m pip uninstall -y numpy scipy opencv-python opencv-python-headless opencv-contrib-python || true
    python3 -m pip install --no-cache-dir --force-reinstall \
        "numpy==1.26.4" \
        "scipy==1.11.4" \
        "opencv-contrib-python==4.8.1.78"

    python3 - <<'PY'
import cv2
import numpy
import scipy
from scipy.spatial.transform import Rotation

print("[OK] numpy", numpy.__version__, numpy.__file__)
print("[OK] scipy", scipy.__version__, scipy.__file__)
print("[OK] cv2", cv2.__version__, cv2.__file__)
print("[OK] scipy Rotation import")
PY

    echo "----------------------------------------"
    echo "Python 数値計算ライブラリの固定完了"
    echo "----------------------------------------"
}



# ============================================#
# ここに実行したいスクリプトを順番に書く      #
# sam3が最初で2番目にpiperが来るようにして    #
# 理由はpipのsetuptoolsのバージョンの問題     #
# sam3は新しいsetuptoolsを必要とするが、      #
# piper以降は古いバージョンでないと動かない   #
# ============================================#
SCRIPTS=(
    "setup/piper.bash"
    "setup/flexbe.bash"
    "setup/realsense.bash"
)
# ==========================================
for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        echo "----------------------------------------"
        echo "$script を実行中..."
        
        # 実行権限がない場合に備えて付与
        chmod +x "$script"
        
        # スクリプトを実行（sourceではなく実行ファイルとして起動）
        ./"$script"
        
        echo "----------------------------------------"
        echo "$script 終了"
        echo "----------------------------------------"
    else
        echo "----------------------------------------"
        echo "[ERROR] $script が見当たらない"
        exit 1
    fi
done

pin_python_versions

echo "----------------------------------------"
echo "--- 終了 ---"
echo "-------------------------------------"
