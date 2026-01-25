#!/usr/bin/env python3
"""
日経新聞RSS要約・LINE通知スクリプト
- RSSフィードから記事を取得
- Gemini APIで要約・分類
- LINE Messaging APIで通知
- Markdown形式で保存
"""

import os
import json
import feedparser
import requests
from google import genai
from datetime import datetime
from pathlib import Path


# 定数
# RSS愛好会の日経新聞フィード（公式RSSは廃止済み）
RSS_URL = "https://assets.wor.jp/rss/rdf/nikkei/news.rdf"
MAX_ARTICLES = 30
CATEGORIES = [
    "経済・景気",
    "政治・政策",
    "テクノロジー・DX",
    "国際情勢",
    "企業・産業",
    "金融・市場",
    "その他"
]


def log(message: str, status: str = "info"):
    """ログ出力"""
    icons = {"success": "✓", "error": "✗", "info": "→"}
    icon = icons.get(status, "→")
    print(f"{icon} {message}")


def fetch_rss() -> list[dict]:
    """RSSフィードから記事を取得"""
    log("RSSフィードを取得中...")
    try:
        feed = feedparser.parse(RSS_URL)
        if feed.bozo and not feed.entries:
            raise Exception(f"RSSパースエラー: {feed.bozo_exception}")

        articles = []
        for entry in feed.entries[:MAX_ARTICLES]:
            articles.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", entry.get("dc_date", "")),
                "summary": entry.get("summary", entry.get("description", ""))
            })

        log(f"{len(articles)}件の記事を取得", "success")
        return articles
    except Exception as e:
        log(f"RSS取得失敗: {e}", "error")
        raise


def summarize_with_gemini(articles: list[dict]) -> dict:
    """Gemini APIで記事を要約・分類"""
    log("Gemini APIで要約・分類中...")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY が設定されていません")

    client = genai.Client(api_key=api_key)

    # 記事リストを作成
    articles_text = "\n\n".join([
        f"【記事{i+1}】\nタイトル: {a['title']}\n概要: {a['summary'] if a['summary'] else '(概要なし)'}"
        for i, a in enumerate(articles)
    ])

    prompt = f"""以下の日経新聞の記事を分析し、JSON形式で出力してください。

【記事一覧】
{articles_text}

【出力形式】
{{
    "categories": {{
        "経済・景気": [
            {{"index": 記事番号, "title": "タイトル", "summary": "2-3行の要約", "importance": 重要度1-5}}
        ],
        "政治・政策": [...],
        "テクノロジー・DX": [...],
        "国際情勢": [...],
        "企業・産業": [...],
        "金融・市場": [...],
        "その他": [...]
    }},
    "top_topics": [
        {{"index": 記事番号, "title": "タイトル", "summary": "要約", "importance": 重要度, "category": "分野"}}
    ]
}}

【指示】
1. 各記事を最も適切な分野に分類してください
2. 各記事について2-3行で要約してください
3. 重要度は★の数(1-5)で評価してください（5が最重要）
4. top_topicsには重要度の高い上位5件を選んでください
5. JSONのみを出力し、他の説明は不要です
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )
        result_text = response.text

        # JSONを抽出（コードブロック対応）
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        result = json.loads(result_text.strip())
        log("要約・分類完了", "success")
        return result
    except json.JSONDecodeError as e:
        log(f"JSON解析エラー: {e}", "error")
        return fallback_categorize(articles)
    except Exception as e:
        log(f"Gemini API エラー: {e}", "error")
        return fallback_categorize(articles)


def fallback_categorize(articles: list[dict]) -> dict:
    """キーワードベースのフォールバック分類"""
    log("フォールバック: キーワードベース分類を実行", "info")

    keywords = {
        "経済・景気": ["GDP", "景気", "消費", "物価", "インフレ", "デフレ", "成長"],
        "政治・政策": ["政府", "首相", "国会", "法案", "選挙", "政党", "内閣"],
        "テクノロジー・DX": ["AI", "DX", "IT", "デジタル", "半導体", "ソフトウェア", "クラウド"],
        "国際情勢": ["米国", "中国", "EU", "外交", "貿易", "国連", "戦争"],
        "企業・産業": ["決算", "売上", "利益", "事業", "新製品", "M&A", "買収"],
        "金融・市場": ["株価", "為替", "日銀", "金利", "投資", "債券", "円安", "円高"]
    }

    categories = {cat: [] for cat in CATEGORIES}
    top_topics = []

    for i, article in enumerate(articles):
        title = article["title"]
        summary = article.get("summary", "")
        text = title + " " + summary

        matched_category = "その他"
        for category, words in keywords.items():
            if any(word in text for word in words):
                matched_category = category
                break

        item = {
            "index": i + 1,
            "title": title,
            "summary": summary[:100] + "..." if len(summary) > 100 else summary,
            "importance": 3
        }
        categories[matched_category].append(item)

        if len(top_topics) < 5:
            top_topics.append({
                "index": i + 1,
                "title": title,
                "summary": item["summary"],
                "importance": 3,
                "category": matched_category
            })

    return {"categories": categories, "top_topics": top_topics}


def send_line_notification(summary_data: dict, articles: list[dict], article_count: int):
    """LINE Messaging APIで通知を送信"""
    log("LINE通知を送信中...")

    channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not channel_token or not user_id:
        log("LINE認証情報が設定されていません", "error")
        return False

    # メッセージ作成
    today = datetime.now().strftime("%Y年%m月%d日")
    top_topics = summary_data.get("top_topics", [])

    message_lines = [
        f"📰 日経新聞 本日のサマリー",
        f"📅 {today}",
        f"📊 本日の記事数: {article_count}件",
        "",
        "🔥 注目トピック TOP5:"
    ]

    for i, topic in enumerate(top_topics[:5], 1):
        stars = "★" * topic.get("importance", 3)
        message_lines.append(f"{i}. [{topic.get('category', '')}] {topic.get('title', '')}")
        message_lines.append(f"   {stars}")
        # 記事のリンクを追加
        idx = topic.get("index", i) - 1
        if 0 <= idx < len(articles):
            message_lines.append(f"   {articles[idx]['link']}")

    message = "\n".join(message_lines)

    # LINE Messaging API Push
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            log("LINE通知送信完了", "success")
            return True
        else:
            log(f"LINE通知エラー: {response.status_code} - {response.text}", "error")
            return False
    except Exception as e:
        log(f"LINE通知例外: {e}", "error")
        return False


def save_markdown(articles: list[dict], summary_data: dict) -> str:
    """Markdown形式で保存"""
    log("Markdown保存中...")

    today = datetime.now()
    filename = today.strftime("%Y-%m-%d") + ".md"
    filepath = Path(__file__).parent.parent / "summaries" / filename

    lines = [
        f"# 日経新聞サマリー - {today.strftime('%Y年%m月%d日')}",
        "",
        f"**生成時刻**: {today.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**記事数**: {len(articles)}件",
        "",
        "---",
        "",
        "## 🔥 注目トピック TOP5",
        ""
    ]

    for i, topic in enumerate(summary_data.get("top_topics", [])[:5], 1):
        stars = "★" * topic.get("importance", 3) + "☆" * (5 - topic.get("importance", 3))
        lines.append(f"### {i}. {topic.get('title', '')}")
        lines.append(f"**分野**: {topic.get('category', '')} | **重要度**: {stars}")
        lines.append(f"> {topic.get('summary', '')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 📂 分野別サマリー")
    lines.append("")

    categories = summary_data.get("categories", {})
    for category in CATEGORIES:
        items = categories.get(category, [])
        if items:
            lines.append(f"### {category}")
            lines.append("")
            for item in items:
                stars = "★" * item.get("importance", 3)
                lines.append(f"- **{item.get('title', '')}** {stars}")
                lines.append(f"  - {item.get('summary', '')}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 📋 全記事一覧")
    lines.append("")

    for i, article in enumerate(articles, 1):
        lines.append(f"{i}. [{article['title']}]({article['link']})")

    content = "\n".join(lines)

    # ディレクトリ作成
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")

    log(f"保存完了: {filepath}", "success")
    return str(filepath)


def send_error_notification(error_message: str):
    """エラー時のLINE通知"""
    channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not channel_token or not user_id:
        return

    message = f"⚠️ 日経新聞サマリー生成エラー\n\n{error_message}"

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}]
    }

    try:
        requests.post(url, headers=headers, json=payload)
    except Exception:
        pass


def main():
    """メイン処理"""
    print("=" * 50)
    print("📰 日経新聞サマリー生成開始")
    print("=" * 50)
    print()

    try:
        # 1. RSS取得
        articles = fetch_rss()

        # 2. Gemini APIで要約
        summary_data = summarize_with_gemini(articles)

        # 3. Markdown保存
        filepath = save_markdown(articles, summary_data)

        # 4. LINE通知
        send_line_notification(summary_data, articles, len(articles))

        print()
        print("=" * 50)
        log("全処理完了", "success")
        print("=" * 50)

    except Exception as e:
        log(f"処理失敗: {e}", "error")
        send_error_notification(str(e))
        raise


if __name__ == "__main__":
    main()
