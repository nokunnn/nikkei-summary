# 📰 日経新聞デイリーサマリー

日経電子版のRSSフィードから記事を自動取得し、Gemini AIで要約・分類してLINEに通知するシステムです。

## ✨ 機能

- 📥 **RSS自動取得**: 日経電子版から最新30件の記事を取得
- 🤖 **AI要約**: Gemini APIで記事を分野別に分類・要約
- ⭐ **重要度評価**: 各記事に★1〜5の重要度を自動付与
- 📱 **LINE通知**: 注目トピックTOP5をLINEにプッシュ通知
- 📄 **Markdown保存**: 要約結果をGitHubに自動保存
- ⏰ **毎日自動実行**: GitHub Actionsで毎朝7時(JST)に実行

## 📁 プロジェクト構成

```
news_summary/
├── .github/workflows/
│   └── daily-summary.yml    # GitHub Actions ワークフロー
├── scripts/
│   ├── summarize.py         # メイン処理スクリプト
│   └── test_local.py        # ローカルテスト用
├── summaries/               # 要約保存ディレクトリ
├── .gitignore
├── .env.example             # 環境変数テンプレート
├── requirements.txt
└── README.md
```

## 🚀 セットアップ

### 1. Google AI Studio APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/app/apikey) にアクセス
2. Googleアカウントでログイン
3. 「Create API Key」をクリック
4. APIキーをコピーして保存

### 2. LINE Messaging API の設定

1. [LINE Developers](https://developers.line.biz/) にログイン
2. 「プロバイダーを作成」→ 任意の名前を入力
3. 「チャンネルを作成」→「Messaging API」を選択
4. チャンネル名・説明を入力して作成
5. 「Messaging API設定」タブで:
   - 「チャンネルアクセストークン（長期）」を発行
   - 「応答設定」で「あいさつメッセージ」「応答メッセージ」をオフに
6. LINE公式アカウントを友だち追加（QRコードから）

### 3. LINE ユーザーIDの取得

**方法A: Webhook経由**
1. チャンネルの「Messaging API設定」でWebhook URLを設定
2. 自分がメッセージを送ると、ユーザーIDがWebhookに送信される

**方法B: LINE Official Account Manager**
1. [LINE Official Account Manager](https://manager.line.biz/) にログイン
2. 作成したアカウントを選択
3. 「チャット」から自分とのトークを開く
4. ユーザー情報からIDを確認

**方法C: 簡易スクリプト**
```python
# get_user_id.py
from flask import Flask, request
app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        print(f"User ID: {event['source']['userId']}")
    return "OK"

if __name__ == "__main__":
    app.run(port=5000)
```
ngrok等で公開し、Webhook URLに設定。LINEでメッセージを送るとユーザーIDが表示されます。

### 4. GitHubリポジトリの設定

1. このリポジトリをForkまたはClone
2. GitHubリポジトリの「Settings」→「Secrets and variables」→「Actions」
3. 以下のシークレットを追加:

| シークレット名 | 値 |
|--------------|---|
| `GOOGLE_API_KEY` | Google AI Studio APIキー |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINEチャンネルアクセストークン |
| `LINE_USER_ID` | 通知先のユーザーID |

### 5. GitHub Actions の有効化

1. リポジトリの「Actions」タブを開く
2. 「I understand my workflows, go ahead and enable them」をクリック

## 💻 ローカルでのテスト

```bash
# 1. 依存関係をインストール
pip install -r requirements.txt

# 2. .envファイルを作成
cp .env.example .env
# .env を編集してAPIキー等を設定

# 3. テスト実行
python scripts/test_local.py
```

## ⏰ 自動実行スケジュール

- **実行時刻**: 毎日 7:00 AM (JST)
- **手動実行**: GitHubの「Actions」タブ →「Daily Nikkei Summary」→「Run workflow」

## 📋 生成される要約の例

```markdown
# 日経新聞サマリー - 2025年01月25日

**生成時刻**: 2025-01-25 07:00:00
**記事数**: 30件

---

## 🔥 注目トピック TOP5

### 1. 日銀、追加利上げを決定
**分野**: 金融・市場 | **重要度**: ★★★★★
> 日本銀行は金融政策決定会合で追加利上げを決定。
> 短期金利の誘導目標を0.5%に引き上げ...

...
```

## 📱 LINE通知の例

```
📰 日経新聞 本日のサマリー
📅 2025年01月25日
📊 本日の記事数: 30件

🔥 注目トピック TOP5:
1. [金融・市場] 日銀、追加利上げを決定
   ★★★★★
2. [テクノロジー・DX] Apple、新型AIチップ発表
   ★★★★☆
...

📄 詳細: https://github.com/user/repo/blob/main/summaries/2025-01-25.md
```

## 💰 コスト情報

**完全無料で運用可能です！**

| サービス | 無料枠 |
|---------|-------|
| Gemini API | 1分あたり15リクエスト（十分） |
| LINE Messaging API | 月200通まで無料 |
| GitHub Actions | 公開リポジトリは無料 |

## 🔧 カスタマイズ

### 取得記事数の変更
`scripts/summarize.py` の `MAX_ARTICLES` を変更:
```python
MAX_ARTICLES = 50  # 30から50に変更
```

### 実行時刻の変更
`.github/workflows/daily-summary.yml` の cron を変更:
```yaml
schedule:
  - cron: '0 21 * * *'  # UTC 21:00 = JST 6:00
```

### 分野カテゴリの変更
`scripts/summarize.py` の `CATEGORIES` を編集:
```python
CATEGORIES = [
    "経済・景気",
    "政治・政策",
    # ... 追加・変更
]
```

## ❓ トラブルシューティング

### RSS取得エラー
- 日経のRSSフィードURLが変更されている可能性があります
- `RSS_URL` を確認・更新してください

### Gemini APIエラー
- APIキーが正しいか確認
- [Google AI Studio](https://aistudio.google.com/) でAPIキーの状態を確認
- 自動的にキーワードベース分類にフォールバックします

### LINE通知が届かない
- チャンネルアクセストークンが正しいか確認
- ユーザーIDが正しいか確認
- LINE公式アカウントを友だち追加しているか確認

### GitHub Actions が動かない
- 「Actions」タブでワークフローが有効か確認
- Secretsが正しく設定されているか確認
- 手動実行でテストしてみる

## 📜 ライセンス

MIT License
