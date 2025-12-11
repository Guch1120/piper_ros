# cotyaka_omega のための FlexBE ステートとビヘイビア

新規プロジェクトで使用するためのビヘイビアリポジトリの汎用テンプレート

プロジェクトの詳細に合わせて、必要に応じてこの README を修正してください。

以下に基本的な詳細を示しますが、この README は自由に削除または変更して構いません。

----

この生の（raw）リポジトリには、汎用名 `cotyaka_omega` を持つフォルダとファイルがいくつか含まれています。

このリポジトリは、FlexBE ウィジェットの [`create_repo`](https://github.com/FlexBE/flexbe_behavior_engine/blob/ros2-devel/flexbe_widget/bin/create_repo) スクリプトによって使用され、独自のステートやビヘイビアを追加するためのベースとなるサンプルプロジェクトを作成します。

`ros2 run flexbe_widget create_repo <my_new_project_name>` を使用すると、このリポジトリが複製され、関連する `cotyaka_omega` のテキストが必要に応じて `my_new_project_name` に変更されます。

これは、適切な FlexBE export タグを使用して `package.xml` ファイルを設定します。
作業の出発点として、バージョン `0.0.1` で維持されています。

ROS のガイドラインに準拠するためにライセンスファイルを提供していますが、`LICENSE` ファイルを置き換え、作成したステートやビヘイビアに対して任意のライセンスを適用することは自由です。

このリポジトリには、サンプルのビヘイビアと、独自のステート実装を作成するための例が含まれています。

## `cotyaka_omega_flexbe_states` 内のステート例

FlexBE ステートを提供するパッケージは、`package.xml` 内の export タグによって識別されます：

```xml
  <export>
      <flexbe_states />
      <build_type>ament_cmake</build_type>
  </export>
```

* `example_state.py `
  * ステートのライフサイクルを表示するための、追加のコンソールログを含むステート実装例。

* `example_action_state.py`

> 注：これらのサンプルステートには、FlexBE の学習に役立つ追加のコンソールログが定義されていますが、通常、これらの例ほど多くの `Logger.info` コマンドを含めることはありません。

> 注：これらのファイルをコピーして修正し、独自のファイルを作成して、独自のライセンス条項の下で公開することは自由です。既存のライセンスに従い、保証は暗示されません。

## `cotyaka_omega_flexbe_behaviors` 内のビヘイビア例

FlexBE ビヘイビアを提供するパッケージは、`package.xml` 内の export タグによって識別されます：

```xml
  <export>
      <flexbe_behaviors />
      <build_type>ament_cmake</build_type>
  </export>
```

  * `example_behavior_sm.py`
    * 最も基本的なステートマシンの例

  * `example_action_behavior_sm.py` 
    * 標準のアクションチュートリアルで `ExampleActionState` を使用します

        [ROS2 アクションの理解 (Understanding ROS2 Actions)](https://docs.ros.org/en/iron/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Actions/Understanding-ROS2-Actions.html)

        [Turtlesim の紹介 (Introducing Turtlesim)](https://docs.ros.org/en/iron/Tutorials/Beginner-CLI-Tools/Introducing-Turtlesim/Introducing-Turtlesim.html)
        
        関連するビヘイビアを FlexBE で実行するには、まずアクションサーバーを提供する turtlesim ノードを実行する必要があります：

        `ros2 run turtlesim turtlesim_node`
        
        利用可能なアクションを表示するには：

        `ros2 action list`
        
        アクションは以下によって定義されます：

        `/turtle1/rotate_absolute:` [`turtlesim/action/RotateAbsolute`](https://docs.ros2.org/latest/api/turtlesim/action/RotateAbsolute.html)

ビヘイビアは通常、FlexBE UI によって編集および生成されます。
これらの生成されたファイルは、ルートワークスペースの `install` フォルダに保存されます。
`WORKSPACE_ROOT` 環境変数が存在することを前提として、保存されたビヘイビア（Python 実装とマニフェスト `.xml` ファイルの両方）を長期保存用にプロジェクトのソースフォルダへコピーするためのシンプルな [`copy_behavior`](cotyaka_omega_flexbe_behaviors/bin/copy_behavior) スクリプトを提供しています。
使用方法を確認するには、`ros2 run cotyaka_omega_flexbe_behavior copy_behavior` を使用してください。
このスクリプトは、このリポジトリのベースフォルダから実行する必要があります。

クイックスタートや FlexBE のより包括的な紹介については、[FlexBE Turtlesim Demonstrations](https://github.com/FlexBE/flexbe_turtlesim_demo) を参照してください。