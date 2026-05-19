import argparse
import json
import os
import re
import shutil
import sys
import time
import socket

import requests
import schedule

from db_manager import DatabaseManager, APP_DATA_DIR, ensure_app_data_dir, migrate_from_script_dir
from deepseek_summarizer import process_new_items, test_api_key
from email_sender import EmailSender
from site_crawlers import ALL_CRAWLERS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DATA_DIR, "config.json")
AUTOSTART_BAT_NAME = "crawl_monitor.bat"
HTML_SAVE_DIR = os.path.join(APP_DATA_DIR, "downloaded_pages")

OLD_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
OLD_HTML_SAVE_DIR = os.path.join(SCRIPT_DIR, "downloaded_pages")

PING_TARGETS = ["www.mee.gov.cn", "www.nhc.gov.cn"]


def check_network_available(host, timeout=2):
    try:
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port = 443
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def wait_for_network(config):
    wait_enabled = config.get("network_wait", {}).get("enabled", True)
    wait_timeout = config.get("network_wait", {}).get("timeout", 5)

    if not wait_enabled:
        print("网络等待功能已禁用，直接开始...")
        return True

    print(f"正在检测网络连接... (超时: {wait_timeout}秒)")

    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        if elapsed > wait_timeout:
            break

        for target in PING_TARGETS:
            if check_network_available(target):
                print(f"网络连接成功！(连接到 {target})")
                return True

        print(f"等待网络中... ({int(elapsed)}秒/{wait_timeout}秒)")
        time.sleep(1)

    print("网络连接超时！")
    while True:
        choice = input("是否重试? (y/n, 默认: y): ").strip().lower() or "y"
        if choice == "y":
            print("重新开始等待网络...")
            return wait_for_network({
                "network_wait": {
                    "enabled": True,
                    "timeout": wait_timeout
                }
            })
        elif choice == "n":
            print("继续尝试爬取...")
            return False


def migrate_legacy_data():
    migrated = []

    if os.path.exists(OLD_CONFIG_PATH) and not os.path.exists(CONFIG_PATH):
        ensure_app_data_dir()
        shutil.copy2(OLD_CONFIG_PATH, CONFIG_PATH)
        migrated.append("config.json")

    db_migrated = migrate_from_script_dir()
    if db_migrated:
        migrated.append("crawl_data.db")

    if os.path.exists(OLD_HTML_SAVE_DIR) and not os.path.exists(HTML_SAVE_DIR):
        ensure_app_data_dir()
        shutil.copytree(OLD_HTML_SAVE_DIR, HTML_SAVE_DIR)
        migrated.append("downloaded_pages/")

    if migrated:
        print(f"已将旧数据迁移至 {APP_DATA_DIR}:")
        for item in migrated:
            print(f"  - {item}")
        print()


def load_config() -> dict | None:
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    changed = False
    if "network_wait" not in config:
        config["network_wait"] = {"enabled": True, "timeout": 5}
        changed = True
    if "download_html" in config and "deepseek_summary" not in config:
        config["deepseek_summary"] = {
            "enabled": config["download_html"],
            "api_key": ""
        }
        del config["download_html"]
        changed = True
    elif "deepseek_summary" not in config:
        config["deepseek_summary"] = {"enabled": False, "api_key": ""}
        changed = True
    if changed:
        save_config(config)
    return config


def save_config(config: dict):
    ensure_app_data_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def interactive_setup() -> dict:
    print("=" * 50)
    print("       网站监控爬虫系统 - 初始化配置")
    print("=" * 50)

    print("\n--- 邮件配置 ---")
    print("常用SMTP服务器:")
    print("  QQ邮箱:   smtp.qq.com   端口 465")
    print("  163邮箱:  smtp.163.com  端口 465")
    print("  Gmail:    smtp.gmail.com 端口 465")

    smtp_server = input("\nSMTP服务器 (默认: smtp.qq.com): ").strip() or "smtp.qq.com"
    smtp_port = input("SMTP端口 (默认: 465): ").strip() or "465"
    sender = input("发件人邮箱: ").strip()
    password = input("授权码 (非邮箱登录密码): ").strip()

    print("\n收件人邮箱 (可输入多个，用逗号分隔):")
    receiver_input = input("收件人邮箱: ").strip()
    receivers = [r.strip() for r in receiver_input.split(",") if r.strip()]

    if not sender or not password or not receivers:
        print("错误: 发件人邮箱、授权码和收件人邮箱不能为空")
        sys.exit(1)

    print("\n--- 定时执行配置 ---")
    enable_schedule = input("是否启用定时执行? (y/n, 默认: n): ").strip().lower() == "y"
    schedule_time = ""
    interval_days = 1
    if enable_schedule:
        schedule_time = input("执行时间 (HH:MM, 默认: 09:00): ").strip() or "09:00"
        interval_input = input("间隔天数 (默认: 1): ").strip()
        if interval_input:
            try:
                interval_days = int(interval_input)
                if interval_days < 1:
                    interval_days = 1
            except ValueError:
                interval_days = 1

    print("\n--- 开机自启动 ---")
    enable_autostart = input("是否启用开机自启动? (y/n, 默认: n): ").strip().lower() == "y"
    autostart_mode = "console"
    if enable_autostart:
        print("自启动模式:")
        print("  1. 控制台模式 (显示命令行窗口，直接运行爬虫)")
        print("  2. 静默模式 (不显示窗口，运行定时调度)")
        print("  3. 运行后确认关闭 (执行一次爬取，显示结果后按回车关闭)")
        mode_choice = input("请选择 (1/2/3, 默认: 1): ").strip()
        if mode_choice == "2":
            autostart_mode = "silent"
        elif mode_choice == "3":
            autostart_mode = "run_once"
        else:
            autostart_mode = "console"

    print("\n--- 网络等待配置 ---")
    enable_network_wait = input("是否启用开机自启动时等待网络? (y/n, 默认: y): ").strip().lower() != "n"
    wait_timeout = 5
    if enable_network_wait:
        wait_input = input("网络等待超时时间(秒) (默认: 5): ").strip()
        if wait_input:
            try:
                wait_timeout = int(wait_input)
                if wait_timeout < 1:
                    wait_timeout = 5
            except ValueError:
                wait_timeout = 5

    print("\n--- DeepSeek智能摘要 ---")
    enable_deepseek = input("是否启用DeepSeek智能摘要? (y/n, 默认: n): ").strip().lower() == "y"
    deepseek_api_key = ""
    if enable_deepseek:
        print("请输入DeepSeek API Key (可在 https://platform.deepseek.com 获取):")
        deepseek_api_key = input("API Key: ").strip()
        if deepseek_api_key:
            print("正在测试API Key...")
            success, msg = test_api_key(deepseek_api_key)
            print(msg)
            if not success:
                print("API Key测试未通过，仍会保存配置，但摘要功能可能无法正常使用。")
        else:
            print("未输入API Key，摘要功能将无法使用。")
            enable_deepseek = False

    config = {
        "email": {
            "smtp_server": smtp_server,
            "smtp_port": int(smtp_port),
            "sender": sender,
            "password": password,
            "receivers": receivers,
        },
        "schedule": {
            "enabled": enable_schedule,
            "time": schedule_time,
            "interval_days": interval_days,
        },
        "autostart": enable_autostart,
        "autostart_mode": autostart_mode,
        "deepseek_summary": {
            "enabled": enable_deepseek,
            "api_key": deepseek_api_key
        },
        "network_wait": {
            "enabled": enable_network_wait,
            "timeout": wait_timeout
        }
    }

    save_config(config)
    print(f"\n配置已保存到 {CONFIG_PATH}")
    return config


def run_crawl_and_notify():
    config = load_config()
    if not config:
        print(f"错误: 未找到配置文件，请先运行: python crawler.py init")
        print(f"配置文件路径: {CONFIG_PATH}")
        return

    db = DatabaseManager()
    email = EmailSender(config["email"])
    deepseek_config = config.get("deepseek_summary", {})
    deepseek_enabled = deepseek_config.get("enabled", False)
    deepseek_api_key = deepseek_config.get("api_key", "")

    all_results = []

    for crawler in ALL_CRAWLERS:
        site_key = crawler.site_key
        site_name = crawler.site_name

        if not db.is_initialized(site_key):
            print(f"警告: [{site_name}] 尚未初始化记录，请先运行初始化")
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "not_initialized",
                    "message": "尚未初始化记录，跳过比对",
                    "new_items": [],
                }
            )
            continue

        try:
            records = crawler.crawl()
        except Exception as e:
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "error",
                    "message": f"爬取失败: {e}",
                    "new_items": [],
                }
            )
            continue

        if not records:
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "error",
                    "message": "爬取结果为空，网站可能无法访问或结构已变化",
                    "new_items": [],
                }
            )
            continue

        existing_urls = db.get_urls(site_key)
        new_items = [(t, u) for t, u in records if u not in existing_urls]

        if not new_items:
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "normal",
                    "message": "爬取正常，无最新通知",
                    "new_items": [],
                }
            )
        else:
            db.insert_records(site_key, new_items)

            summaries = {}
            if deepseek_enabled and deepseek_api_key:
                summary_results = process_new_items(
                    new_items, site_key, site_name, deepseek_api_key
                )
                for title, url, summary in summary_results:
                    summaries[url] = summary

            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "update",
                    "message": f"发现 {len(new_items)} 条新通知",
                    "new_items": new_items,
                    "summaries": summaries,
                }
            )

    subject, body = compose_email(all_results)

    try:
        email.send(subject, body)
        print("邮件已发送")
    except Exception as e:
        print(f"邮件发送失败: {e}")

    print("\n" + body)


def compose_email(results: list[dict]) -> tuple[str, str]:
    total_new = 0
    has_error = False
    body_parts = []

    for result in results:
        site_name = result["site_name"]
        status = result["status"]

        if status == "error":
            has_error = True
            body_parts.append(f"【{site_name}】\n状态：异常\n{result['message']}\n")
        elif status == "normal":
            body_parts.append(f"【{site_name}】\n状态：正常\n{result['message']}\n")
        elif status == "update":
            new_count = len(result["new_items"])
            total_new += new_count
            summaries = result.get("summaries", {})
            items_lines = []
            for i, (t, u) in enumerate(result["new_items"], 1):
                items_lines.append(f"  {i}. {t}")
                items_lines.append(f"     {u}")
                if u in summaries and summaries[u]:
                    items_lines.append(f"     摘要：{summaries[u]}")
            items_text = "\n".join(items_lines)
            body_parts.append(f"【{site_name}】\n{items_text}\n")
        elif status == "not_initialized":
            has_error = True
            body_parts.append(f"【{site_name}】\n状态：未初始化\n{result['message']}\n")

    status_text = "异常" if has_error else "正常"
    subject = f"法规监控报告-{total_new}条新通知-程序运行状态{status_text}"
    body = "\n".join(body_parts)

    return subject, body


def init_records():
    config = load_config()
    if config:
        choice = input("已存在配置文件，是否重新配置? (y/n, 默认: n): ").strip().lower()
        if choice == "y":
            config = interactive_setup()
    else:
        config = interactive_setup()

    db = DatabaseManager()

    for crawler in ALL_CRAWLERS:
        site_key = crawler.site_key
        site_name = crawler.site_name

        if db.is_initialized(site_key):
            count = db.get_record_count(site_key)
            choice = input(
                f"[{site_name}] 已有 {count} 条记录，是否重新初始化? (y/n, 默认: n): "
            ).strip().lower()
            if choice != "y":
                print(f"[{site_name}] 跳过初始化")
                continue
            db.clear_records(site_key)

        print(f"\n正在初始化 [{site_name}] ...")
        try:
            records = crawler.crawl()
            if records:
                db.insert_records(site_key, records)
                print(f"[{site_name}] 已存储 {len(records)} 条记录")
            else:
                print(f"[{site_name}] 爬取结果为空，请检查网站是否可访问")
        except Exception as e:
            print(f"[{site_name}] 爬取失败: {e}")

    if config.get("autostart"):
        setup_autostart(True)

    if config.get("schedule", {}).get("enabled"):
        interval = config["schedule"].get("interval_days", 1)
        time_str = config["schedule"].get("time", "09:00")
        if interval == 1:
            print(f"\n定时执行已配置，每日 {time_str} 执行")
        else:
            print(f"\n定时执行已配置，每 {interval} 天 {time_str} 执行")
        print("运行以下命令启动定时任务: python crawler.py start")

    print("\n初始化完成!")


def _get_exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return sys.executable


def setup_autostart(enable: bool, mode: str | None = None):
    startup_folder = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )
    bat_path = os.path.join(startup_folder, AUTOSTART_BAT_NAME)

    if enable:
        config = load_config()
        if mode is None:
            mode = config.get("autostart_mode", "console") if config else "console"

        exe_path = _get_exe_path()

        if getattr(sys, "frozen", False):
            if mode == "silent":
                bat_content = f'@echo off\nstart "" /min "{exe_path}" --autostart-run\n'
            elif mode == "run_once":
                bat_content = f'@echo off\n"{exe_path}" --autostart-run-once\npause\n'
            else:
                bat_content = f'@echo off\n"{exe_path}" --autostart-run\n'
        else:
            python_exe = sys.executable
            if mode == "silent":
                pythonw_exe = python_exe.replace("python.exe", "pythonw.exe")
                exe_to_use = pythonw_exe if os.path.exists(pythonw_exe) else python_exe
                bat_content = f'@echo off\nstart "" /min "{exe_to_use}" "{SCRIPT_DIR}\\crawler.py" --autostart-run\n'
            elif mode == "run_once":
                bat_content = f'@echo off\n"{python_exe}" "{SCRIPT_DIR}\\crawler.py" --autostart-run-once\npause\n'
            else:
                bat_content = f'@echo off\n"{python_exe}" "{SCRIPT_DIR}\\crawler.py" --autostart-run\n'

        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        mode_names = {"console": "控制台模式", "silent": "静默模式", "run_once": "运行后确认关闭模式"}
        print(f"已添加开机自启动 ({mode_names.get(mode, mode)}): {bat_path}")

        if config:
            config["autostart"] = True
            config["autostart_mode"] = mode
            save_config(config)
    else:
        if os.path.exists(bat_path):
            os.remove(bat_path)
            print("已移除开机自启动")
        else:
            print("未找到开机自启动项")

        config = load_config()
        if config:
            config["autostart"] = False
            save_config(config)


def start_scheduler():
    config = load_config()
    if not config:
        print(f"错误: 未找到配置文件，请先运行: python crawler.py init")
        print(f"配置文件路径: {CONFIG_PATH}")
        return

    schedule_config = config.get("schedule", {})
    if not schedule_config.get("enabled"):
        print("定时执行未启用。")
        print(f"请运行 'python crawler.py init' 配置定时执行，或手动编辑 {CONFIG_PATH}")
        return

    schedule_time = schedule_config.get("time", "09:00")
    interval_days = schedule_config.get("interval_days", 1)

    if interval_days == 1:
        schedule.every().day.at(schedule_time).do(run_crawl_and_notify)
        print(f"定时任务已启动，每日 {schedule_time} 自动执行爬取并通知")
    else:
        schedule.every(interval_days).days.at(schedule_time).do(run_crawl_and_notify)
        print(f"定时任务已启动，每 {interval_days} 天 {schedule_time} 自动执行爬取并通知")

    print("按 Ctrl+C 退出\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n定时任务已停止")


def test_compare_and_push():
    config = load_config()
    if not config:
        print("错误: 未找到配置文件，请先运行初始化")
        return

    db = DatabaseManager()
    email = EmailSender(config["email"])
    deepseek_config = config.get("deepseek_summary", {})
    deepseek_enabled = deepseek_config.get("enabled", False)
    deepseek_api_key = deepseek_config.get("api_key", "")

    print("=" * 50)
    print("       测试比对与推送功能")
    print("=" * 50)

    all_results = []

    for crawler in ALL_CRAWLERS:
        site_key = crawler.site_key
        site_name = crawler.site_name

        if not db.is_initialized(site_key):
            print(f"\n[{site_name}] 数据库无记录，跳过测试")
            continue

        count = db.get_record_count(site_key)
        print(f"\n[{site_name}] 当前记录数: {count}")

        deleted_record = db.delete_latest_record(site_key)
        if not deleted_record:
            print(f"[{site_name}] 无法删除记录，跳过")
            continue

        deleted_title, deleted_url = deleted_record
        print(f"[{site_name}] 已删除最新记录:")
        print(f"  标题: {deleted_title}")
        print(f"  链接: {deleted_url}")

        try:
            records = crawler.crawl()
        except Exception as e:
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "error",
                    "message": f"爬取失败: {e}",
                    "new_items": [],
                }
            )
            db.insert_records(site_key, [deleted_record])
            continue

        if not records:
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "error",
                    "message": "爬取结果为空",
                    "new_items": [],
                }
            )
            db.insert_records(site_key, [deleted_record])
            continue

        existing_urls = db.get_urls(site_key)
        new_items = [(t, u) for t, u in records if u not in existing_urls]

        if deleted_url in [u for t, u in new_items]:
            print(f"\n[测试通过] 删除的记录被正确识别为新记录!")
            db.insert_records(site_key, new_items)

            summaries = {}
            if deepseek_enabled and deepseek_api_key:
                summary_results = process_new_items(
                    new_items, site_key, site_name, deepseek_api_key
                )
                for title, url, summary in summary_results:
                    summaries[url] = summary

            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "update",
                    "message": f"测试成功: 发现 {len(new_items)} 条新通知（含被删除的记录）",
                    "new_items": new_items,
                    "summaries": summaries,
                }
            )
        else:
            print(f"\n[测试异常] 删除的记录未被识别为新记录")
            db.insert_records(site_key, [deleted_record])
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "normal",
                    "message": "测试异常: 删除的记录未被识别为新记录",
                    "new_items": [],
                }
            )

    if not all_results:
        print("\n没有可测试的网站")
        return

    subject, body = compose_email(all_results)

    print("\n" + "-" * 40)
    print("邮件内容预览:")
    print("-" * 40)
    print(f"主题: {subject}")
    print(f"\n{body}")

    try:
        email.send(subject, body)
        print("\n邮件已发送")
    except Exception as e:
        print(f"\n邮件发送失败: {e}")


def config_deepseek():
    config = load_config()
    if not config:
        print("未找到配置文件，请先运行: python crawler.py init")
        return

    deepseek_config = config.get("deepseek_summary", {})
    current_enabled = deepseek_config.get("enabled", False)
    current_key = deepseek_config.get("api_key", "")

    print("=" * 50)
    print("       DeepSeek智能摘要配置")
    print("=" * 50)
    print(f"当前状态: {'已启用' if current_enabled else '已禁用'}")
    if current_key:
        print(f"当前API Key: {current_key[:8]}...{current_key[-4:]}")

    enable = input("\n是否启用DeepSeek智能摘要? (y/n, 默认: n): ").strip().lower() == "y"
    api_key = ""
    if enable:
        if current_key:
            change_key = input("是否更换API Key? (y/n, 默认: n): ").strip().lower() == "y"
            if change_key:
                print("请输入新的DeepSeek API Key:")
                api_key = input("API Key: ").strip()
            else:
                api_key = current_key
        else:
            print("请输入DeepSeek API Key (可在 https://platform.deepseek.com 获取):")
            api_key = input("API Key: ").strip()

        if api_key:
            print("正在测试API Key...")
            success, msg = test_api_key(api_key)
            print(msg)
            if not success:
                print("API Key测试未通过，仍会保存配置，但摘要功能可能无法正常使用。")
        else:
            print("未输入API Key，摘要功能将无法使用。")
            enable = False

    config["deepseek_summary"] = {
        "enabled": enable,
        "api_key": api_key if api_key else current_key
    }
    save_config(config)
    print(f"\nDeepSeek智能摘要已{'启用' if enable else '禁用'}")
    print(f"配置已保存到 {CONFIG_PATH}")


def show_config():
    config = load_config()
    if not config:
        print("未找到配置文件，请先运行: python crawler.py init")
        return

    display = json.loads(json.dumps(config))
    if "email" in display and "password" in display["email"]:
        display["email"]["password"] = "******"
    if "deepseek_summary" in display and "api_key" in display["deepseek_summary"]:
        key = display["deepseek_summary"]["api_key"]
        if key:
            display["deepseek_summary"]["api_key"] = f"{key[:8]}...{key[-4:]}"

    print(json.dumps(display, ensure_ascii=False, indent=4))
    print(f"\n数据目录: {APP_DATA_DIR}")


def show_main_menu():
    config = load_config()
    has_config = config is not None

    print("\n" + "=" * 50)
    print("         网站监控爬虫系统")
    print("=" * 50)

    options = [
        ("初始化配置并存储记录", True),
        ("立即执行爬取并邮件通知", has_config),
        ("启动定时调度器", has_config),
        ("测试比对与推送功能", has_config),
        ("DeepSeek智能摘要配置", has_config),
        ("开启开机自启动", has_config),
        ("关闭开机自启动", True),
        ("查看当前配置", has_config),
        ("退出程序", True),
    ]

    print("\n请选择操作：")
    for i, (text, available) in enumerate(options, 1):
        if available:
            print(f"  {i}. {text}")
        else:
            print(f"  {i}. {text} (需先初始化)")

    return options


def interactive_menu():
    while True:
        options = show_main_menu()

        try:
            choice = input("\n请输入选项编号: ").strip()
            if not choice:
                continue
            num = int(choice)
        except ValueError:
            print("输入无效，请输入数字")
            continue

        if num < 1 or num > len(options):
            print(f"请输入 1-{len(options)} 之间的数字")
            continue

        text, available = options[num - 1]
        if not available:
            print("该选项需要先执行初始化（选项1）")
            continue

        if num == 1:
            print("\n" + "-" * 40)
            init_records()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 2:
            print("\n" + "-" * 40)
            run_crawl_and_notify()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 3:
            print("\n" + "-" * 40)
            start_scheduler()
            print("-" * 40)
        elif num == 4:
            print("\n" + "-" * 40)
            test_compare_and_push()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 5:
            print("\n" + "-" * 40)
            config_deepseek()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 6:
            print("\n" + "-" * 40)
            print("请选择自启动模式:")
            print("  1. 控制台模式 (显示命令行窗口，直接运行爬虫)")
            print("  2. 静默模式 (不显示窗口，运行定时调度)")
            print("  3. 运行后确认关闭 (执行一次爬取，显示结果后按回车关闭)")
            mode_choice = input("请选择 (1/2/3, 默认: 1): ").strip()
            if mode_choice == "2":
                mode = "silent"
            elif mode_choice == "3":
                mode = "run_once"
            else:
                mode = "console"
            setup_autostart(True, mode)
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 7:
            print("\n" + "-" * 40)
            setup_autostart(False)
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 8:
            print("\n" + "-" * 40)
            show_config()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 9:
            print("\n再见！")
            break


def main():
    migrate_legacy_data()

    config = load_config()

    if "--autostart-run" in sys.argv:
        if config and config.get("autostart_mode") != "silent":
            print("开机自启动：直接执行爬取...")
            wait_for_network(config)
            run_crawl_and_notify()
            input("\n按回车键关闭程序...")
        else:
            print("开机自启动：启动定时调度器...")
            wait_for_network(config)
            start_scheduler()
        return

    if "--autostart-run-once" in sys.argv:
        wait_for_network(config)
        run_crawl_and_notify()
        input("\n按回车键关闭程序...")
        return

    if len(sys.argv) > 1 and sys.argv[1] not in ["--autostart-run", "--autostart-run-once"]:
        parser = argparse.ArgumentParser(description="网站监控爬虫系统")
        subparsers = parser.add_subparsers(dest="command")

        subparsers.add_parser("init", help="初始化：交互配置 + 存储初始记录")
        subparsers.add_parser("run", help="立即执行爬取，比对数据库，邮件通知")
        subparsers.add_parser("start", help="启动定时调度器（前台运行）")

        autostart_parser = subparsers.add_parser("autostart", help="管理开机自启动")
        autostart_parser.add_argument("action", choices=["on", "off"], help="on=开启, off=关闭")

        subparsers.add_parser("config", help="查看当前配置")
        subparsers.add_parser("deepseek", help="配置DeepSeek智能摘要")

        args = parser.parse_args()

        if args.command == "init":
            init_records()
        elif args.command == "run":
            run_crawl_and_notify()
        elif args.command == "start":
            start_scheduler()
        elif args.command == "autostart":
            setup_autostart(args.action == "on")
        elif args.command == "config":
            show_config()
        elif args.command == "deepseek":
            config_deepseek()
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
