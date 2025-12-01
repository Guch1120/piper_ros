#!/bin/bash
# setup_all.sh

# エラーが発生したらそこでスクリプトを止める設定（これ大事だよ）
set -e

# ==========================================
# ここに実行したいスクリプトを順番に書いてね
# ==========================================
SCRIPTS=(
    "setup_detic.bash"
    "setup_flexbe.bash"
    "setup_realsense.bash"
    "setup_piper.bash"
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
        
        echo "$script 終了"
    else
        echo "----------------------------------------"
        echo "[ERROR] $script が見当たらない"
        exit 1
    fi
done

echo "----------------------------------------"
echo "--- 終了 ---"
echo "-------------------------------------"