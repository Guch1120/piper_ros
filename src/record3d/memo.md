# システムライブラリのインストール
# libusbmuxd-dev: iOSとの通信に必須
# usbutils: USBデバッグ用
RUN apt-get update && apt-get install -y \
    libusbmuxd-dev \
    usbutils \

# docker起動コマンドの確認，なければ追加
-v /var/run/usbmuxd:/var/run/usbmuxd: ホストのiOS通信用ソケットを共有

# 実行は
python /app/record3d_src/receive_stream.py