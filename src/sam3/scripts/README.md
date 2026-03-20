# 実行手順
1.  引数でカメラ座標と世界座標を設定しておく
```bash
ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 --yaw 0 --pitch 0 --roll 0 --frame-id map --child-frame-id camera_link
```
2. 画像座標からカメラ座標、ワールド座標を計算し、TFを発行するプログラム
```bash
python3 TF_magcup.py 
```

3. 画像座標、depthをトピックで送信するサブスクライバー
```bash
python3 magucup_image_depth_pub.py 
```


`ros2 run tf2_ros static_transform_publisher --x 0 --y 0 --z 0 --yaw 0 --pitch 0 --roll 0 --frame-id map --child-frame-id camera_link`は、「ロボット（カメラ）が、地図上のどこに固定されているか」を定義するコマンドです。 \
ROSの世界では、すべての物体が「親」とつながっている必要があります。このコマンドは、孤立していたカメラ（camera_link）を、地図の原点（map）に「接着」する役割を果たしています。 \
各引数の意味を詳しく解説します。 \

## プログラムでしている指定
```bash
ros2 run tf2_ros static_transform_publisher
```
tf2_ros パッケージの中にある static_transform_publisher というツールを実行します。 \
Static（静的） とは、「時間が経っても動かない関係」という意味です。カメラを三脚などで固定している場合に使います。（逆にタイヤなどは動くので使いません） \

- 1.位置と姿勢（Transform）
ここは「親（map）」から見た「子（camera）」のズレを指定します。今回はすべて 0 なので、「地図の原点とカメラの位置・向きは完全に一致している」と定義しています。 \
```bash
--x 0 --y 0 --z 0
# 位置（メートル） です。
# もしカメラを「1メートル前（x）、1.5メートル高い位置（z）」に置いた場合は --x 1.0 --z 1.5 とします。
--yaw 0 --pitch 0 --roll 0
# 回転（ラジアン） です。
# Yaw（水平回転）、Pitch（上下首振り）、Roll（傾き）です。
# 0 なので、地図の「北」とカメラの「正面」が同じ向きであると定義しています。
```
- 3.親子の関係（Frame ID）
ここが今回の一番のポイントです。
```bash
--frame-id map
# 親フレーム（Parent） です。基準となる座標系です。今回はワールド座標（地図）を指定しました。
--child-frame-id camera_link
# 子フレーム（Child） です。親にくっつける対象です。
```
なぜこれで解決するのか？（家系図のイメージ） \
直前のエラーは「親の取り合い」でした。それを回避するために、このコマンドで以下のような正しい「家系図」を作りました。 

map（親玉：このコマンドで指定） \
↓ （このコマンドがつなぐ！） \
camera_link（カメラ本体の基準点） \
↓ （RealSenseドライバが自動でつなぐ） \
camera_color_frame \
↓ （RealSenseドライバが自動でつなぐ） \
camera_color_optical_frame（レンズの中心：認識に使う場所） 

このように、一番根元である camera_link を map につなぐことで、末端にある camera_color_optical_frame まで一本道がつながり、「カメラで見つけたマグカップの座標」を「地図上の座標」へ変換できるようになったのです。 

