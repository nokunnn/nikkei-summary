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
import anthropic
from google import genai
from datetime import datetime
from pathlib import Path
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def generate_content_with_retry(client, model, prompt):
    """Gemini API呼び出し（リトライ付き）"""
    return client.models.generate_content(
        model=model,
        contents=prompt
    )


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
    "daily_trend": {{
        "summary": "本日のニュース全体を俯瞰した3-5行のトレンド分析。複数の記事に共通するテーマや、今日特に注目すべき動向をまとめる。",
        "keywords": ["キーワード1", "キーワード2", "キーワード3"]
    }},
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
    "top_topics": {{
        "social": [
            {{"index": 記事番号, "title": "タイトル", "summary": "要約", "importance": 重要度, "category": "分野"}}
        ],
        "personal": [
            {{"index": 記事番号, "title": "タイトル", "summary": "要約", "importance": 重要度, "category": "分野"}}
        ]
    }}
}}

【指示】
1. daily_trendには、本日の記事全体を俯瞰し、複数の記事から読み取れるトレンドや共通テーマを分析してください
2. 各記事を最も適切な分野に分類してください
3. 各記事について2-3行で要約してください
4. 重要度は★の数(1-5)で評価してください（5が最重要）
5. top_topicsは以下の2グループに分けて選んでください：
   - social（社会的に重要なニュース）: 経済・景気・政治・政策・文化・社会に関連するニュースから重要度の高い3件を選んでください
   - personal（個人に特化した重要なニュース）: AI・データサイエンス・コンサルティング・航空業界・交通業界に関連するニュースから重要度の高い3件を選んでください。該当するニュースがない場合は、テクノロジー・DXや企業・産業から代替として選んでください
6. JSONのみを出力し、他の説明は不要です
"""

    try:
        response = generate_content_with_retry(
            client,
            "gemini-3-flash-preview",
            prompt
        )
        result_text = response.text

        # JSONを抽出（コードブロック対応）
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        result = json.loads(result_text.strip())

        # daily_trendがない場合はデフォルト値を設定
        if "daily_trend" not in result:
            result["daily_trend"] = {
                "summary": "トレンド分析は取得できませんでした。",
                "keywords": []
            }

        result["model"] = "Gemini 3 Flash"
        log("要約・分類完了", "success")
        return result
    except json.JSONDecodeError as e:
        log(f"JSON解析エラー: {e}", "error")
        log(f"受信テキスト(先頭500文字): {result_text[:500] if result_text else 'empty'}", "error")
        return summarize_with_anthropic(articles)
    except Exception as e:
        log(f"Gemini API エラー: {e}", "error")
        return summarize_with_anthropic(articles)


def summarize_with_anthropic(articles: list[dict]) -> dict:
    """Anthropic Claude APIで記事を要約・分類（Geminiのフォールバック）"""
    log("Anthropic APIで要約・分類中（フォールバック）...")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY が設定されていません", "error")
        return fallback_categorize(articles)

    client = anthropic.Anthropic(api_key=api_key)

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
    "daily_trend": {{
        "summary": "本日のニュース全体を俯瞰した3-5行のトレンド分析。複数の記事に共通するテーマや、今日特に注目すべき動向をまとめる。",
        "keywords": ["キーワード1", "キーワード2", "キーワード3"]
    }},
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
    "top_topics": {{
        "social": [
            {{"index": 記事番号, "title": "タイトル", "summary": "要約", "importance": 重要度, "category": "分野"}}
        ],
        "personal": [
            {{"index": 記事番号, "title": "タイトル", "summary": "要約", "importance": 重要度, "category": "分野"}}
        ]
    }}
}}

【指示】
1. daily_trendには、本日の記事全体を俯瞰し、複数の記事から読み取れるトレンドや共通テーマを分析してください
2. 各記事を最も適切な分野に分類してください
3. 各記事について2-3行で要約してください
4. 重要度は★の数(1-5)で評価してください（5が最重要）
5. top_topicsは以下の2グループに分けて選んでください：
   - social（社会的に重要なニュース）: 経済・景気・政治・政策・文化・社会に関連するニュースから重要度の高い3件を選んでください
   - personal（個人に特化した重要なニュース）: AI・データサイエンス・コンサルティング・航空業界・交通業界に関連するニュースから重要度の高い3件を選んでください。該当するニュースがない場合は、テクノロジー・DXや企業・産業から代替として選んでください
6. JSONのみを出力し、他の説明は不要です"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = response.content[0].text

        # JSONを抽出（コードブロック対応）
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        # 制御文字を除去（JSON解析エラー対策）
        import re
        result_text = re.sub(r'[\x00-\x1f\x7f]', '', result_text.strip())

        result = json.loads(result_text)

        # daily_trendがない場合はデフォルト値を設定
        if "daily_trend" not in result:
            result["daily_trend"] = {
                "summary": "トレンド分析は取得できませんでした。",
                "keywords": []
            }

        result["model"] = "Claude Sonnet 4"
        log("要約・分類完了（Anthropic）", "success")
        return result
    except json.JSONDecodeError as e:
        log(f"JSON解析エラー（Anthropic）: {e}", "error")
        log(f"受信テキスト(先頭1000文字): {result_text[:1000] if result_text else 'empty'}", "error")
        return fallback_categorize(articles)
    except Exception as e:
        log(f"Anthropic API エラー: {e}", "error")
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

    personal_keywords = ["AI", "人工知能", "データ", "コンサルティング", "コンサル", "航空", "交通", "空港", "鉄道", "物流"]

    categories = {cat: [] for cat in CATEGORIES}
    social_topics = []
    personal_topics = []

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

        topic = {
            "index": i + 1,
            "title": title,
            "summary": item["summary"],
            "importance": 3,
            "category": matched_category
        }

        if any(word in text for word in personal_keywords) and len(personal_topics) < 3:
            personal_topics.append(topic)
        elif matched_category in ("経済・景気", "政治・政策", "その他") and len(social_topics) < 3:
            social_topics.append(topic)

    # 不足分を補完
    for i, article in enumerate(articles):
        if len(social_topics) >= 3 and len(personal_topics) >= 2:
            break
        topic = {
            "index": i + 1,
            "title": article["title"],
            "summary": article.get("summary", "")[:100],
            "importance": 3,
            "category": "その他"
        }
        if len(social_topics) < 3 and topic not in social_topics:
            social_topics.append(topic)
        elif len(personal_topics) < 2 and topic not in personal_topics:
            personal_topics.append(topic)

    # フォールバック時のトレンド
    daily_trend = {
        "summary": "本日のニューストレンドは自動分析できませんでした。",
        "keywords": []
    }

    return {"daily_trend": daily_trend, "categories": categories, "top_topics": {"social": social_topics[:3], "personal": personal_topics[:3]}, "model": "キーワードベース"}


CATEGORIES_EN = {
    "経済・景気": "Economy",
    "政治・政策": "Politics & Policy",
    "テクノロジー・DX": "Technology & DX",
    "国際情勢": "International Affairs",
    "企業・産業": "Business & Industry",
    "金融・市場": "Finance & Markets",
    "その他": "Other"
}


def translate_with_gemini(summary_data: dict) -> dict:
    """Gemini APIで要約データを英語に翻訳"""
    log("Gemini APIで英語翻訳中...")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY が設定されていません")

    client = genai.Client(api_key=api_key)

    # modelキーを除外してJSON化
    data_to_translate = {k: v for k, v in summary_data.items() if k != "model"}
    json_text = json.dumps(data_to_translate, ensure_ascii=False, indent=2)

    prompt = f"""Translate the following Japanese news summary JSON into English.
Translate all text values (summary, title, keywords, category names) into natural English.
Keep the JSON structure exactly the same. Output only valid JSON.

Category name mapping:
- 経済・景気 → Economy
- 政治・政策 → Politics & Policy
- テクノロジー・DX → Technology & DX
- 国際情勢 → International Affairs
- 企業・産業 → Business & Industry
- 金融・市場 → Finance & Markets
- その他 → Other

{json_text}"""

    try:
        response = generate_content_with_retry(
            client,
            "gemini-3-flash-preview",
            prompt
        )
        result_text = response.text

        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        result = json.loads(result_text.strip())
        result["model"] = summary_data.get("model", "")
        log("英語翻訳完了（Gemini）", "success")
        return result
    except Exception as e:
        log(f"Gemini翻訳エラー: {e}", "error")
        return translate_with_anthropic(summary_data)


def translate_with_anthropic(summary_data: dict) -> dict:
    """Anthropic APIで要約データを英語に翻訳（フォールバック）"""
    log("Anthropic APIで英語翻訳中（フォールバック）...")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY が設定されていません", "error")
        return summary_data

    client = anthropic.Anthropic(api_key=api_key)

    data_to_translate = {k: v for k, v in summary_data.items() if k != "model"}
    json_text = json.dumps(data_to_translate, ensure_ascii=False, indent=2)

    prompt = f"""Translate the following Japanese news summary JSON into English.
Translate all text values (summary, title, keywords, category names) into natural English.
Keep the JSON structure exactly the same. Output only valid JSON.

Category name mapping:
- 経済・景気 → Economy
- 政治・政策 → Politics & Policy
- テクノロジー・DX → Technology & DX
- 国際情勢 → International Affairs
- 企業・産業 → Business & Industry
- 金融・市場 → Finance & Markets
- その他 → Other

{json_text}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        result_text = response.content[0].text

        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        import re
        result_text = re.sub(r'[\x00-\x1f\x7f]', '', result_text.strip())

        result = json.loads(result_text)
        result["model"] = summary_data.get("model", "")
        log("英語翻訳完了（Anthropic）", "success")
        return result
    except Exception as e:
        log(f"Anthropic翻訳エラー: {e}", "error")
        return summary_data


def translate_to_english(summary_data: dict) -> dict:
    """要約データを英語に翻訳（Gemini優先、Anthropicフォールバック）"""
    return translate_with_gemini(summary_data)


def send_line_notification(summary_data: dict, articles: list[dict], article_count: int, summary_data_en: dict = None):
    """LINE Messaging APIで通知を送信"""
    log("LINE通知を送信中...")

    channel_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not channel_token or not user_id:
        log("LINE認証情報が設定されていません", "error")
        return False

    # メッセージ作成
    today = datetime.now().strftime("%Y年%m月%d日")
    top_topics = summary_data.get("top_topics", {})
    social_topics = top_topics.get("social", []) if isinstance(top_topics, dict) else top_topics[:3]
    personal_topics = top_topics.get("personal", []) if isinstance(top_topics, dict) else top_topics[3:5]
    daily_trend = summary_data.get("daily_trend", {})
    trend_summary = daily_trend.get("summary", "")
    model_name = summary_data.get("model", "不明")

    message_lines = [
        "おはようございます！",
        "",
        f"📰 日経新聞 本日のサマリー",
        f"📅 {today}",
        f"📊 本日の記事数: {article_count}件",
        f"🤖 使用モデル: {model_name}",
        "",
        "📈 本日のトレンド:",
        trend_summary,
        "",
        "🌏 社会的に重要なニュース:"
    ]

    for i, topic in enumerate(social_topics[:3], 1):
        stars = "★" * topic.get("importance", 3)
        message_lines.append(f"{i}. [{topic.get('category', '')}] {topic.get('title', '')}")
        message_lines.append(f"   {stars}")
        idx = topic.get("index", i) - 1
        if 0 <= idx < len(articles):
            message_lines.append(f"   {articles[idx]['link']}")

    message_lines.extend(["", "👤 個人に特化した重要なニュース:"])

    for i, topic in enumerate(personal_topics[:3], 1):
        stars = "★" * topic.get("importance", 3)
        message_lines.append(f"{i}. [{topic.get('category', '')}] {topic.get('title', '')}")
        message_lines.append(f"   {stars}")
        idx = topic.get("index", i) - 1
        if 0 <= idx < len(articles):
            message_lines.append(f"   {articles[idx]['link']}")

    # 英語版サマリーを追加
    if summary_data_en:
        top_topics_en = summary_data_en.get("top_topics", {})
        social_topics_en = top_topics_en.get("social", []) if isinstance(top_topics_en, dict) else top_topics_en[:3]
        personal_topics_en = top_topics_en.get("personal", []) if isinstance(top_topics_en, dict) else top_topics_en[3:5]
        daily_trend_en = summary_data_en.get("daily_trend", {})
        trend_summary_en = daily_trend_en.get("summary", "")

        message_lines.extend([
            "",
            "--- English Summary ---",
            "",
            "Today's Trend:",
            trend_summary_en,
            "",
            "🌏 Socially Important News:"
        ])

        for i, topic in enumerate(social_topics_en[:3], 1):
            stars = "★" * topic.get("importance", 3)
            message_lines.append(f"{i}. [{topic.get('category', '')}] {topic.get('title', '')}")
            message_lines.append(f"   {stars}")

        message_lines.extend(["", "👤 Personally Relevant News:"])

        for i, topic in enumerate(personal_topics_en[:3], 1):
            stars = "★" * topic.get("importance", 3)
            message_lines.append(f"{i}. [{topic.get('category', '')}] {topic.get('title', '')}")
            message_lines.append(f"   {stars}")

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

    # トレンド情報を取得
    daily_trend = summary_data.get("daily_trend", {})
    trend_summary = daily_trend.get("summary", "")
    trend_keywords = daily_trend.get("keywords", [])

    lines = [
        f"# 日経新聞サマリー - {today.strftime('%Y年%m月%d日')}",
        "",
        f"**生成時刻**: {today.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**記事数**: {len(articles)}件",
        "",
        "---",
        "",
        "## 📊 本日のトレンド",
        "",
        trend_summary,
        ""
    ]

    if trend_keywords:
        lines.append(f"**キーワード**: {', '.join(trend_keywords)}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 🔥 注目トピック",
        ""
    ])

    top_topics = summary_data.get("top_topics", {})
    social_topics = top_topics.get("social", []) if isinstance(top_topics, dict) else top_topics[:3]
    personal_topics = top_topics.get("personal", []) if isinstance(top_topics, dict) else top_topics[3:5]

    lines.extend(["### 🌏 社会的に重要なニュース", ""])
    for i, topic in enumerate(social_topics[:3], 1):
        stars = "★" * topic.get("importance", 3) + "☆" * (5 - topic.get("importance", 3))
        lines.append(f"#### {i}. {topic.get('title', '')}")
        lines.append(f"**分野**: {topic.get('category', '')} | **重要度**: {stars}")
        lines.append(f"> {topic.get('summary', '')}")
        lines.append("")

    lines.extend(["### 👤 個人に特化した重要なニュース", ""])
    for i, topic in enumerate(personal_topics[:3], 1):
        stars = "★" * topic.get("importance", 3) + "☆" * (5 - topic.get("importance", 3))
        lines.append(f"#### {i}. {topic.get('title', '')}")
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


def save_markdown_en(articles: list[dict], summary_data_en: dict) -> str:
    """英語版Markdown形式で保存"""
    log("英語版Markdown保存中...")

    today = datetime.now()
    filename = today.strftime("%Y-%m-%d") + ".md"
    filepath = Path(__file__).parent.parent / "summaries_en" / filename

    daily_trend = summary_data_en.get("daily_trend", {})
    trend_summary = daily_trend.get("summary", "")
    trend_keywords = daily_trend.get("keywords", [])

    lines = [
        f"# Nikkei News Summary - {today.strftime('%B %d, %Y')}",
        "",
        f"**Generated at**: {today.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Articles**: {len(articles)}",
        "",
        "---",
        "",
        "## Today's Trends",
        "",
        trend_summary,
        ""
    ]

    if trend_keywords:
        lines.append(f"**Keywords**: {', '.join(trend_keywords)}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Top Topics",
        ""
    ])

    top_topics_en = summary_data_en.get("top_topics", {})
    social_topics_en = top_topics_en.get("social", []) if isinstance(top_topics_en, dict) else top_topics_en[:3]
    personal_topics_en = top_topics_en.get("personal", []) if isinstance(top_topics_en, dict) else top_topics_en[3:5]

    lines.extend(["### 🌏 Socially Important News", ""])
    for i, topic in enumerate(social_topics_en[:3], 1):
        stars = "★" * topic.get("importance", 3) + "☆" * (5 - topic.get("importance", 3))
        lines.append(f"#### {i}. {topic.get('title', '')}")
        lines.append(f"**Category**: {topic.get('category', '')} | **Importance**: {stars}")
        lines.append(f"> {topic.get('summary', '')}")
        lines.append("")

    lines.extend(["### 👤 Personally Relevant News", ""])
    for i, topic in enumerate(personal_topics_en[:3], 1):
        stars = "★" * topic.get("importance", 3) + "☆" * (5 - topic.get("importance", 3))
        lines.append(f"#### {i}. {topic.get('title', '')}")
        lines.append(f"**Category**: {topic.get('category', '')} | **Importance**: {stars}")
        lines.append(f"> {topic.get('summary', '')}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Summary by Category")
    lines.append("")

    categories = summary_data_en.get("categories", {})
    for category_ja in CATEGORIES:
        category_en = CATEGORIES_EN.get(category_ja, category_ja)
        # 翻訳後のデータでは英語カテゴリ名で格納されている可能性があるため両方チェック
        items = categories.get(category_en, categories.get(category_ja, []))
        if items:
            lines.append(f"### {category_en}")
            lines.append("")
            for item in items:
                stars = "★" * item.get("importance", 3)
                lines.append(f"- **{item.get('title', '')}** {stars}")
                lines.append(f"  - {item.get('summary', '')}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## All Articles")
    lines.append("")

    for i, article in enumerate(articles, 1):
        lines.append(f"{i}. [{article['title']}]({article['link']})")

    content = "\n".join(lines)

    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")

    log(f"英語版保存完了: {filepath}", "success")
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

        # 2. Gemini APIで日本語要約
        summary_data = summarize_with_gemini(articles)

        # 3. 英語翻訳
        summary_data_en = translate_to_english(summary_data)

        # 4. 日本語Markdown保存
        filepath = save_markdown(articles, summary_data)

        # 5. 英語Markdown保存
        filepath_en = save_markdown_en(articles, summary_data_en)

        # 6. LINE通知（日本語+英語）
        send_line_notification(summary_data, articles, len(articles), summary_data_en)

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
