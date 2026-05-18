#! usr/bin/bash

set -e
# ログイン huggingface
echo " Login to HuggingFace"
echo "login huggingface by Token Guch1(2026-04-03 Yamaguchi Takuma)"
python3 login_huggingface.py
echo "Login to HuggingFace completed"

# モデルをダウンロード
python3 sam3_download_model_and_bpe.py