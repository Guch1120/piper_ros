# エラー対応集
各エラーに対してトグルで対処法を表示．

<!--  コピペ用 -->
<!-- <details>
<summary>対処</summary>
</details> -->

```
adb devices 
List of devices attached
4A080DLAQ002AF	unauthorized
```

<details>
<summary>対処</summary>

スマホ側で許可するというウィンドウが出ているので許可を押す．
出ていなければケーブルを抜き差しして再度表示させる．
</details>


```
oit_kobuki_ws/kobuki_controller$ HOME=/tmp
  FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter devices
  bash: /tmp/flutter-sdk/bin/flutter: そのようなファイルやディレクトリはありません
```
<details>
<summary>対処</summary>

```bash
git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /tmp/flutter-sdk
```
</details>


```
HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter run
Downloading Material fonts...                                      344ms
Downloading Gradle Wrapper...                                      135ms
Downloading package sky_engine...                                   91ms
Downloading package flutter_gpu...                                  29ms
Downloading flutter_patched_sdk tools...                           203ms
Downloading flutter_patched_sdk_product tools...                   165ms
Downloading linux-x64 tools...                                   2,436ms
Downloading linux-x64/font-subset tools...                         221ms
Downloading android-arm-profile/linux-x64 tools...               1,077ms
Downloading android-arm-release/linux-x64 tools...                 953ms
Downloading android-arm64-profile/linux-x64 tools...             1,055ms
Downloading android-arm64-release/linux-x64 tools...             1,008ms
Downloading android-x64-profile/linux-x64 tools...               1,053ms
Downloading android-x64-release/linux-x64 tools...                 991ms
Downloading Web SDK...                                           2,279ms
Downloading linux-x64-debug/linux-x64-flutter-gtk tools...          3.3s
Downloading linux-x64-profile/linux-x64-flutter-gtk tools...      1,955ms
Downloading linux-x64-release/linux-x64-flutter-gtk tools...      1,514ms
Resolving dependencies... 
Downloading packages... (1.0s)
  meta 1.17.0 (1.18.2 available)
  test_api 0.7.10 (0.7.11 available)
  vector_math 2.2.0 (2.3.0 available)
Got dependencies!
3 packages have newer versions incompatible with dependency constraints.
Try `flutter pub outdated` for more information.
Launching lib/main.dart on Pixel 9 in debug mode...

FAILURE: Build failed with an exception.

* Where:
Build file '/home/robo25/yamaguchi/oit_kobuki_ws/kobuki_controller/android/app/build.gradle.kts' line: 1

* What went wrong:
An exception occurred applying plugin request [id: 'com.android.application']
> Failed to apply plugin 'com.android.internal.application'.
   > Android Gradle plugin requires Java 17 to run. You are currently using Java 11.
      Your current JDK is located in /usr/lib/jvm/java-11-openjdk-amd64
      You can try some of the following options:
       - changing the IDE settings.
       - changing the JAVA_HOME environment variable.
       - changing `org.gradle.java.home` in `gradle.properties`.

* Try:
> Run with --stacktrace option to get the stack trace.
> Run with --info or --debug option to get more log output.
> Run with --scan to get full insights.
> Get more help at https://help.gradle.org.

BUILD FAILED in 1m 47s
Running Gradle task 'assembleDebug'...                            108.5s

┌─ Flutter Fix ───────────────────────────────────────────────────────────────────────┐
│ [!] Android Gradle plugin requires Java 17 to run. You are currently using Java 11. │
│                                                                                     │
│ To fix this issue, try updating to the latest Android SDK and Android Studio on:    │
│ https://developer.android.com/studio/install                                        │
│ If that does not work, you can set the Java version used by Flutter by              │
│ running `flutter config --jdk-dir=“</path/to/jdk>“`                                 │
│                                                                                     │
│ To check the Java version used by Flutter, run `flutter doctor --verbose`           │
└─────────────────────────────────────────────────────────────────────────────────────┘
Error: Gradle task assembleDebug failed with exit code 1
```

<details>
<summary>対処</summary>

要求されたjaveバージョンがインストールされていない．今回はjava17が必要だがjava11しか入ってなかった．
`apt-get update`から
```bash
sudo apt-get install -y openjdk-17-jdk
```
</details>

```
HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter run
Launching lib/main.dart on Pixel 9 in debug mode...
Checking the license for package NDK (Side by side) 28.2.13676358 in /usr/lib/android-sdk/licenses
Warning: License for package NDK (Side by side) 28.2.13676358 not accepted.

FAILURE: Build failed with an exception.

* Where:
Build file '/home/robo25/yamaguchi/oit_kobuki_ws/kobuki_controller/android/build.gradle.kts' line: 19

* What went wrong:
A problem occurred configuring project ':app'.
> com.android.builder.sdk.LicenceNotAcceptedException: Failed to install the following Android SDK packages as some licences have not been accepted.
     ndk;28.2.13676358 NDK (Side by side) 28.2.13676358
  To build this project, accept the SDK license agreements and install the missing components using the Android Studio SDK Manager.
  All licenses can be accepted using the sdkmanager command line tool:
  sdkmanager.bat --licenses
  Or, to transfer the license agreements from one workstation to another, see https://developer.android.com/studio/intro/update.html#download-with-gradle

  Using Android SDK: /usr/lib/android-sdk

* Try:
> Run with --stacktrace option to get the stack trace.
> Run with --info or --debug option to get more log output.
> Run with --scan to get full insights.
> Get more help at https://help.gradle.org.

BUILD FAILED in 20s
Running Gradle task 'assembleDebug'...                             21.0s
Error: Gradle task assembleDebug failed with exit code 1
```

<details>
<summary>対処</summary>

NDKのライセンス未認証が原因．
```bash
find /usr/lib/android-sdk -path '*cmdline-tools*' -name sdkmanager | sed -n '1,20p'
```
と
```bash
yes | /usr/lib/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses
```
の2つを実行して確認してみる．何も出力されなければインストールするとこから． \
今回はインストールされていなかったので以下の1~3の手順でインストールした． \
インストールされている場合はすまないが自力で調べて頑張ってくれ．


### 1.command-line tools を入れる
```bash
cd ~
  wget https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip -O commandlinetools-
  linux.zip
  rm -rf /tmp/android-cmdline-tools
  mkdir -p /tmp/android-cmdline-tools
  unzip -q commandlinetools-linux.zip -d /tmp/android-cmdline-tools
  sudo mkdir -p /usr/lib/android-sdk/cmdline-tools
  sudo rm -rf /usr/lib/android-sdk/cmdline-tools/latest
  sudo mv /tmp/android-cmdline-tools/cmdline-tools /usr/lib/android-sdk/cmdline-tools/latest
```

### 2.ライセンス承諾と必要 SDK 導入
```bash
  export ANDROID_HOME=/usr/lib/android-sdk
  export ANDROID_SDK_ROOT=/usr/lib/android-sdk
  /usr/lib/android-sdk/cmdline-tools/latest/bin/sdkmanager --sdk_root=/usr/lib/android-sdk --licenses
  sudo /usr/lib/android-sdk/cmdline-tools/latest/bin/sdkmanager --sdk_root=/usr/lib/android-sdk "platform-tools" "platforms;android-36" "build-tools;36.0.0" "ndk;28.2.13676358"
```
`/usr/lib/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses`ではyes/noを聞かれるのでyを連打． \
7回ぐらい聞かれる．7回ともyを押して最後に`All SDK package licenses accepted`が出ればOK.


### 3.Flutter実行
```bash
cd ~/yamaguchi/oit_kobuki_ws/kobuki_controller
  export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
  export PATH=$JAVA_HOME/bin:$PATH
  export ANDROID_HOME=/usr/lib/android-sdk
  export ANDROID_SDK_ROOT=/usr/lib/android-sdk
  HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter doctor --verbose
  HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter run
```

</details>












事前準備
  Android 側で 開発者向けオプション と USBデバッグ を ON にして、USB で PC に接続してくださ
  い。初回は端末側に出る USBデバッグを許可 を許可します。

  1. アプリを端末へインストール
  まず端末が見えているか確認します。

  adb devices

  見えていれば、アプリをビルドして端末へ入れます。

  cd /home/robo25/yamaguchi/oit_kobuki_ws/kobuki_controller
  HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter devices
  HOME=/tmp FLUTTER_SUPPRESS_ANALYTICS=true /tmp/flutter-sdk/bin/flutter run

  flutter run が通れば、インストールと起動まで一気に行われます。
  もし /tmp/flutter-sdk が消えていたら先にこれを実行してください。

  git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /tmp/flutter-sdk

  2. PC側で動かすもの
  ターミナルを3つ使ってください。

  ターミナルA: Docker 起動

  cd /home/robo25/yamaguchi/oit_kobuki_ws
  docker compose up -d

  ターミナルB: BLE サーバー起動

  cd /home/robo25/yamaguchi/oit_kobuki_ws
  docker compose exec ros2_humble bash -lc "cd /home/user25/kobuki_ws && bash bash_dir/
  ble_server.sh"

  ターミナルC: /cmd_vel 監視

  cd /home/robo25/yamaguchi/oit_kobuki_ws
  docker compose exec ros2_humble bash -lc "set +u; source /opt/ros/humble/setup.bash; ros2
  topic echo /cmd_vel"

  Wi-Fi 接続も試すなら、さらにターミナルDで rosbridge を起動します。

  cd /home/robo25/yamaguchi/oit_kobuki_ws
  docker compose exec ros2_humble bash -lc "cd /home/user25/kobuki_ws && bash bash_dir/
  rosbridge.sh"

  3. 接続方法: BLE
  アプリ起動後に以下を操作してください。

  - Connection Settings を開く
  - BLE を選ぶ
  - Scan BLE devices を押す
  - KobukiController を選ぶ
  - Connect BLE を押す
  - つながったら D-Pad かジョイスティックを操作する

  確認ポイント:

  - ターミナルB に BLE 接続ログが出るか
  - ターミナルC の /cmd_vel に値が流れるか

  4. 接続方法: Wi-Fi
  まず PC の IP を確認します。

  hostname -I

  アプリ側で:

  - Connection Settings を開く
  - Wi-Fi を選ぶ
  - Host に PC の IP を入れる
  - Port は 9090
  - Connect Wi-Fi を押す
  - D-Pad かジョイスティックを操作する













