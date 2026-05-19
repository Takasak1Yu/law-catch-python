import os
import re
import requests

from db_manager import APP_DATA_DIR, ensure_app_data_dir

HTML_SAVE_DIR = os.path.join(APP_DATA_DIR, "downloaded_pages")

PROVIDERS = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
    },
}

DEFAULT_SUMMARY_PROMPT = (
    "你是一个专业的政策法规文书摘要助手。"
    "用户会提供一份政府通知或法规文件的HTML内容，"
    "请你阅读并提取其中的核心信息，生成一段简要总结。"
    "要求：1）总结不超过200字；2）重点包含文件的核心要求、关键时间节点、适用范围等实质内容；"
    "3）如果文件涉及申报、备案、审批等行政事项，需说明具体要求和截止日期；"
    "4）用简洁的书面语表述，不要使用列表格式，直接输出一段连续文本。"
)

KEYWORD_FILTER_PROMPT = (
    "你是一个内容相关性判断助手。"
    "用户会提供一份政府通知或法规文件的内容，以及一组关键词。"
    "请你判断该文件内容是否与用户给出的关键词相关。"
    "关键词代表用户关注的主题领域，只要文件内容涉及关键词所指向的主题即可判定为相关。"
    "请严格按照以下格式回复，不要输出任何其他内容：\n"
    "- 如果相关，回复：RELATED\n"
    "- 如果不相关，回复：UNRELATED"
)

BLOCKLIST_FILTER_PROMPT = (
    "你是一个内容屏蔽判断助手。"
    "用户会提供一份政府通知或法规文件的内容，以及一组屏蔽词。"
    "请你判断该文件内容是否涉及用户给出的屏蔽词所指向的主题。"
    "屏蔽词代表用户不希望看到的内容领域，只要文件内容涉及屏蔽词所指向的主题即应判定为需要屏蔽。"
    "请严格按照以下格式回复，不要输出任何其他内容：\n"
    "- 如果涉及屏蔽词主题，回复：BLOCKED\n"
    "- 如果不涉及，回复：PASS"
)


def _get_api_config(provider: str, model: str | None) -> tuple[str, str]:
    provider_key = provider if provider in PROVIDERS else "deepseek"
    provider_info = PROVIDERS[provider_key]
    api_url = provider_info["url"]
    actual_model = model if model else provider_info["default_model"]
    return api_url, actual_model


def _call_api(api_url: str, api_key: str, model: str, messages: list[dict],
              max_tokens: int = 300, temperature: float = 0.3) -> str | None:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError:
        print(f"  API请求失败 (HTTP {resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"  API调用异常: {e}")
        return None


def _extract_text(html_content: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)

    if len(text) > 8000:
        text = text[:8000]

    return text


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


def check_keyword_relevance(
    api_url: str, api_key: str, model: str,
    html_content: str, keywords: list[str], custom_prompt: str | None = None,
) -> bool | None:
    text = _extract_text(html_content)
    if not text:
        return None

    prompt = custom_prompt if custom_prompt else KEYWORD_FILTER_PROMPT
    keywords_str = "、".join(keywords)
    user_msg = f"关键词：{keywords_str}\n\n文件内容：\n{text}"

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_msg},
    ]

    result = _call_api(api_url, api_key, model, messages, max_tokens=10, temperature=0)
    if result is None:
        return None

    if "UNRELATED" in result.upper():
        return False
    if "RELATED" in result.upper():
        return True

    return None


def check_blocklist(
    api_url: str, api_key: str, model: str,
    html_content: str, blockwords: list[str], custom_prompt: str | None = None,
) -> bool | None:
    text = _extract_text(html_content)
    if not text:
        return None

    prompt = custom_prompt if custom_prompt else BLOCKLIST_FILTER_PROMPT
    blockwords_str = "、".join(blockwords)
    user_msg = f"屏蔽词：{blockwords_str}\n\n文件内容：\n{text}"

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_msg},
    ]

    result = _call_api(api_url, api_key, model, messages, max_tokens=10, temperature=0)
    if result is None:
        return None

    if "BLOCKED" in result.upper():
        return True
    if "PASS" in result.upper():
        return False

    return None


def summarize_html(
    api_url: str, api_key: str, model: str,
    html_content: str, custom_prompt: str | None = None,
) -> str | None:
    text = _extract_text(html_content)
    if not text:
        return None

    prompt = custom_prompt if custom_prompt else DEFAULT_SUMMARY_PROMPT

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"请总结以下文件内容：\n\n{text}"},
    ]

    return _call_api(api_url, api_key, model, messages, max_tokens=300, temperature=0.3)


def process_new_items(
    new_items: list[tuple[str, str]],
    site_key: str,
    site_name: str,
    ai_config: dict,
) -> list[tuple[str, str, str | None, bool]]:
    provider = ai_config.get("provider", "deepseek")
    api_key = ai_config.get("api_key", "")
    model = ai_config.get("model", None)
    api_url, actual_model = _get_api_config(provider, model)

    keyword_enabled = ai_config.get("keyword_filter", {}).get("enabled", False)
    keywords = ai_config.get("keyword_filter", {}).get("keywords", [])
    keyword_prompt = ai_config.get("keyword_filter", {}).get("custom_prompt", None)

    blocklist_enabled = ai_config.get("blocklist_filter", {}).get("enabled", False)
    blockwords = ai_config.get("blocklist_filter", {}).get("blockwords", [])
    blocklist_prompt = ai_config.get("blocklist_filter", {}).get("custom_prompt", None)

    summary_prompt = ai_config.get("summary_prompt", None)

    print(f"\n[{site_name}] 下载新数据页面并处理...")

    downloaded = download_html_files(new_items, site_key)

    results = []
    for title, url, filepath in downloaded:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                html_content = f.read()

            filtered_out = False

            if keyword_enabled and keywords:
                print(f"  关键词筛选: {title[:40]}...")
                is_relevant = check_keyword_relevance(
                    api_url, api_key, actual_model,
                    html_content, keywords, keyword_prompt,
                )
                if is_relevant is False:
                    print(f"  [关键词不相关] 跳过: {title[:40]}")
                    filtered_out = True
                elif is_relevant is None:
                    print(f"  [关键词筛选失败] 保留: {title[:40]}")
                else:
                    print(f"  [关键词相关] 继续: {title[:40]}")

            if not filtered_out and blocklist_enabled and blockwords:
                print(f"  屏蔽词筛选: {title[:40]}...")
                is_blocked = check_blocklist(
                    api_url, api_key, actual_model,
                    html_content, blockwords, blocklist_prompt,
                )
                if is_blocked is True:
                    print(f"  [屏蔽词命中] 跳过: {title[:40]}")
                    filtered_out = True
                elif is_blocked is None:
                    print(f"  [屏蔽词筛选失败] 保留: {title[:40]}")
                else:
                    print(f"  [屏蔽词未命中] 继续: {title[:40]}")

            if filtered_out:
                os.remove(filepath)
                print(f"  已删除本地HTML文件")
                results.append((title, url, None, True))
                continue

            print(f"  正在生成摘要: {title[:40]}...")
            summary = summarize_html(
                api_url, api_key, actual_model,
                html_content, summary_prompt,
            )

            if summary:
                print(f"  摘要生成成功")
                os.remove(filepath)
                print(f"  已删除本地HTML文件")
            else:
                print(f"  摘要生成失败，保留HTML文件: {filepath}")

            results.append((title, url, summary, False))
        except Exception as e:
            print(f"  处理失败 [{title[:30]}]: {e}")
            results.append((title, url, None, False))

    return results


def test_api_key(api_key: str, provider: str = "deepseek", model: str | None = None) -> tuple[bool, str]:
    api_url, actual_model = _get_api_config(provider, model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": actual_model,
        "messages": [
            {"role": "user", "content": "你好，请回复'连接成功'"},
        ],
        "max_tokens": 20,
        "temperature": 0,
    }

    provider_name = "DeepSeek" if provider == "deepseek" else "OpenAI"

    try:
        resp = requests.post(api_url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return True, f"{provider_name} API连接测试成功 (模型: {actual_model})"
        elif resp.status_code == 401:
            return False, f"{provider_name} API Key无效，请检查后重试"
        elif resp.status_code == 402:
            return False, f"{provider_name} API账户余额不足，请充值后重试"
        else:
            return False, f"{provider_name} API返回错误 (HTTP {resp.status_code}): {resp.text[:200]}"
    except requests.exceptions.ConnectionError:
        return False, f"无法连接到{provider_name} API服务器，请检查网络"
    except requests.exceptions.Timeout:
        return False, f"连接{provider_name} API超时，请稍后重试"
    except Exception as e:
        return False, f"测试失败: {e}"
