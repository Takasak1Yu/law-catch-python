import os
import re
import requests

from db_manager import APP_DATA_DIR, ensure_app_data_dir

HTML_SAVE_DIR = os.path.join(APP_DATA_DIR, "downloaded_pages")

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

SYSTEM_PROMPT = (
    "你是一个专业的政策法规文书摘要助手。"
    "用户会提供一份政府通知或法规文件的HTML内容，"
    "请你阅读并提取其中的核心信息，生成一段简要总结。"
    "要求：1）总结不超过200字；2）重点包含文件的核心要求、关键时间节点、适用范围等实质内容；"
    "3）如果文件涉及申报、备案、审批等行政事项，需说明具体要求和截止日期；"
    "4）用简洁的书面语表述，不要使用列表格式，直接输出一段连续文本。"
)


def download_html_files(new_items: list[tuple[str, str]], site_key: str) -> list[tuple[str, str, str]]:
    ensure_app_data_dir()
    site_dir = os.path.join(HTML_SAVE_DIR, site_key)
    os.makedirs(site_dir, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    downloaded = []
    for title, url in new_items:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding

            safe_title = re.sub(r'[\\/:*?"<>|]', "_", title[:80])
            filename = f"{safe_title}.html"
            filepath = os.path.join(site_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(resp.text)

            downloaded.append((title, url, filepath))
            print(f"  已下载: {filename}")
        except Exception as e:
            print(f"  下载失败 [{title[:30]}]: {e}")

    return downloaded


def summarize_html(api_key: str, html_content: str) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)

    if len(text) > 8000:
        text = text[:8000]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请总结以下文件内容：\n\n{text}"},
        ],
        "max_tokens": 300,
        "temperature": 0.3,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        summary = data["choices"][0]["message"]["content"].strip()
        return summary
    except requests.exceptions.HTTPError as e:
        print(f"  DeepSeek API请求失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  DeepSeek API调用异常: {e}")
        return None


def process_new_items(
    new_items: list[tuple[str, str]],
    site_key: str,
    site_name: str,
    api_key: str,
) -> list[tuple[str, str, str | None]]:
    print(f"\n[{site_name}] 下载新数据页面并生成摘要...")

    downloaded = download_html_files(new_items, site_key)

    results = []
    for title, url, filepath in downloaded:
        print(f"  正在生成摘要: {title[:40]}...")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                html_content = f.read()

            summary = summarize_html(api_key, html_content)

            if summary:
                print(f"  摘要生成成功")
                os.remove(filepath)
                print(f"  已删除本地HTML文件")
            else:
                print(f"  摘要生成失败，保留HTML文件: {filepath}")

            results.append((title, url, summary))
        except Exception as e:
            print(f"  处理失败 [{title[:30]}]: {e}")
            results.append((title, url, None))

    return results


def test_api_key(api_key: str) -> tuple[bool, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": "你好，请回复'连接成功'"},
        ],
        "max_tokens": 20,
        "temperature": 0,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return True, "API连接测试成功"
        elif resp.status_code == 401:
            return False, "API Key无效，请检查后重试"
        elif resp.status_code == 402:
            return False, "API账户余额不足，请充值后重试"
        else:
            return False, f"API返回错误 (HTTP {resp.status_code}): {resp.text[:200]}"
    except requests.exceptions.ConnectionError:
        return False, "无法连接到DeepSeek API服务器，请检查网络"
    except requests.exceptions.Timeout:
        return False, "连接DeepSeek API超时，请稍后重试"
    except Exception as e:
        return False, f"测试失败: {e}"
