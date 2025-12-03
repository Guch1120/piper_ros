#!/usr/bin/env python3
"""
Google Colab対応セルを更新するスクリプト
既存のColabセルを削除し、より堅牢な新しいセットアップセルに置き換えます。
"""
import json
import sys
from pathlib import Path

# 削除対象のセルID
REMOVE_IDS = [
    "colab-setup-md",
    "colab-check",
    "colab-install",
    "colab-drive",
    "colab-upload-md"
]

# 新しいColab対応セルの定義
NEW_COLAB_CELLS = [
    {
        "cell_type": "markdown",
        "id": "colab-setup-md",
        "metadata": {},
        "source": [
            "## Google Colab セットアップ\n",
            "\n",
            "Google Colabで実行する場合は、以下のセルを実行してください。\n",
            "これにより、必要なライブラリのインストールと、データの読み込み準備が行われます。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "id": "colab-setup-code",
        "metadata": {},
        "outputs": [],
        "source": [
            "# Google Colab環境のセットアップ\n",
            "try:\n",
            "    import google.colab\n",
            "    IN_COLAB = True\n",
            "    print(\"Google Colab環境で実行中\")\n",
            "except ImportError:\n",
            "    IN_COLAB = False\n",
            "    print(\"ローカル環境で実行中\")\n",
            "\n",
            "if IN_COLAB:\n",
            "    # 1. Google Driveをマウント (推奨)\n",
            "    # 自分のデータやコードを使用する場合は、Google Driveにアップロードしてマウントします\n",
            "    from google.colab import drive\n",
            "    drive.mount('/content/drive')\n",
            "    \n",
            "    # 2. SAM3のインストールとパス設定\n",
            "    import os\n",
            "    import sys\n",
            "    \n",
            "    # Google Drive内のSAM3ディレクトリのパス\n",
            "    # ※ご自身の環境に合わせてパスを変更してください\n",
            "    DRIVE_SAM3_PATH = \"/content/drive/MyDrive/sam3\"\n",
            "    \n",
            "    if os.path.exists(DRIVE_SAM3_PATH):\n",
            "        print(f\"Google Drive内のSAM3が見つかりました: {DRIVE_SAM3_PATH}\")\n",
            "        os.chdir(DRIVE_SAM3_PATH)\n",
            "        print(\"カレントディレクトリを変更しました。\")\n",
            "        \n",
            "        # 依存関係のインストール\n",
            "        print(\"依存関係をインストールしています...\")\n",
            "        # Numpy 2.0との互換性問題を回避するためにバージョンを固定\n",
            "        !pip install -q \"numpy<2.0\"\n",
            "        !pip install -q -e .\n",
            "        !pip install -q pycocotools\n",
            "        \n",
            "    else:\n",
            "        print(f\"Google Drive内に {DRIVE_SAM3_PATH} が見つかりませんでした。\")\n",
            "        print(\"GitHubからSAM3をクローンしてインストールします...\")\n",
            "        \n",
            "        # GitHubからクローン\n",
            "        if not os.path.exists(\"/content/sam3\"):\n",
            "            !git clone https://github.com/facebookresearch/sam3.git /content/sam3\n",
            "            \n",
            "        os.chdir(\"/content/sam3\")\n",
            "        print(\"カレントディレクトリを /content/sam3 に変更しました。\")\n",
            "        \n",
            "        # 依存関係のインストール\n",
            "        # Numpy 2.0との互換性問題を回避するためにバージョンを固定\n",
            "        !pip install -q \"numpy<2.0\"\n",
            "        !pip install -q -e .\n",
            "        !pip install -q pycocotools\n",
            "    \n",
            "    print(\"セットアップが完了しました。\")\n",
            "    print(f\"現在の作業ディレクトリ: {os.getcwd()}\")"
        ]
    },
    {
        "cell_type": "markdown",
        "id": "colab-data-usage",
        "metadata": {},
        "source": [
            "### データの使用について\n",
            "\n",
            "- **Google Driveを使用する場合**: `GT_DIR` や `PRED_DIR` には `/content/drive/MyDrive/...` から始まるパスを指定してください。\n",
            "- **GitHubからクローンした場合**: 左側のファイルブラウザから `/content/sam3` 内を確認できます。データは別途アップロードが必要です。"
        ]
    }
]


def update_colab_support(notebook_path):
    """既存のnotebookのColab対応セルを更新"""
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
    
    cells = nb.get('cells', [])
    
    # 1. 古いColabセルを削除
    new_cells = [c for c in cells if c.get('id') not in REMOVE_IDS]
    
    # 2. 挿入位置を決定 (最初のマークダウンセルの後)
    insert_pos = 2
    for i, cell in enumerate(new_cells[:5]):
        if cell.get('cell_type') == 'markdown':
            source = ''.join(cell.get('source', []))
            if '#' in source and ('概要' in source or 'Example' in source or 'Evaluation' in source):
                insert_pos = i + 1
                break
    
    # 3. 新しいセルを挿入
    for i, colab_cell in enumerate(NEW_COLAB_CELLS):
        new_cells.insert(insert_pos + i, colab_cell)
    
    nb['cells'] = new_cells
    
    # ファイルに書き戻す
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
    
    print(f"🔄 {notebook_path.name}: Colab対応を更新しました")
    return True


def main():
    examples_dir = Path('/home/guch1/ssd_yamaguchi/sam3/examples')
    notebooks = list(examples_dir.glob('*.ipynb'))
    
    print(f"📝 {len(notebooks)}個のnotebookのColab設定を更新します...\n")
    
    count = 0
    for notebook_path in sorted(notebooks):
        if update_colab_support(notebook_path):
            count += 1
    
    print(f"\n✨ 完了: {count}/{len(notebooks)}個のnotebookを更新しました")


if __name__ == '__main__':
    main()
