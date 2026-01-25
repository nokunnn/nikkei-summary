#!/usr/bin/env python3
"""
ローカルテスト用スクリプト
.envファイルから環境変数を読み込んでsummarize.pyを実行
"""

import sys
from pathlib import Path

# .envファイルを読み込む
try:
    from dotenv import load_dotenv
except ImportError:
    print("python-dotenv がインストールされていません")
    print("pip install python-dotenv を実行してください")
    sys.exit(1)

# プロジェクトルートの.envを読み込む
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ .envファイルを読み込みました: {env_path}")
else:
    print(f"⚠ .envファイルが見つかりません: {env_path}")
    print("  .env.example をコピーして .env を作成してください")
    sys.exit(1)

# summarize.pyをインポートして実行
from summarize import main

if __name__ == "__main__":
    main()
