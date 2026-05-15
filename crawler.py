import argparse
import json
import os
import re
import sys
import time

import requests
import schedule

from db_manager import DatabaseManager
from email_sender import EmailSender
from site_crawlers import ALL_CRAWLERS

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
AUTOSTART_BAT_NAME = "crawl_monitor.bat"
HTML_SAVE_DIR = os.path.join(SCRIPT_DIR, "downloaded_pages")


def load_config() -> dict | None:
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
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
        print("  1. 控制台模式 (显示命令行窗口)")
        print("  2. 静默模式 (不显示窗口)")
        print("  3. 运行后确认关闭 (执行一次爬取，显示结果后按回车关闭)")
        mode_choice = input("请选择 (1/2/3, 默认: 1): ").strip()
        if mode_choice == "2":
            autostart_mode = "silent"
        elif mode_choice == "3":
            autostart_mode = "run_once"
        else:
            autostart_mode = "console"

    print("\n--- 附加功能 ---")
    enable_download = input("是否启用新数据HTML页面下载? (y/n, 默认: n): ").strip().lower() == "y"

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
        "download_html": enable_download,
    }

    save_config(config)
    print("\n配置已保存到 config.json")
    return config


def download_new_pages(new_items: list[tuple[str, str]], site_key: str):
    if not new_items:
        return

    site_dir = os.path.join(HTML_SAVE_DIR, site_key)
    os.makedirs(site_dir, exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    for title, url in new_items:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = resp.apparent_encoding

            safe_title = re.sub(r'[\\/:*?"<>|]', "_", title[:80])
            filename = f"{safe_title}.html"
            filepath = os.path.join(site_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(resp.text)

            print(f"  已下载: {filename}")
        except Exception as e:
            print(f"  下载失败 [{title[:30]}]: {e}")


def run_crawl_and_notify():
    config = load_config()
    if not config:
        print("错误: 未找到配置文件，请先运行: python crawler.py init")
        return

    db = DatabaseManager()
    email = EmailSender(config["email"])
    download_enabled = config.get("download_html", False)

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
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "update",
                    "message": f"发现 {len(new_items)} 条新通知",
                    "new_items": new_items,
                }
            )

            if download_enabled:
                print(f"\n[{site_name}] 下载新数据页面...")
                download_new_pages(new_items, site_key)

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
            items_text = "\n".join(
                f"  {i}. {t}\n     {u}"
                for i, (t, u) in enumerate(result["new_items"], 1)
            )
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
        print("错误: 未找到配置文件，请先运行: python crawler.py init")
        return

    schedule_config = config.get("schedule", {})
    if not schedule_config.get("enabled"):
        print("定时执行未启用。")
        print("请运行 'python crawler.py init' 配置定时执行，或手动编辑 config.json")
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
    download_enabled = config.get("download_html", False)

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
            all_results.append(
                {
                    "site_name": site_name,
                    "site_key": site_key,
                    "status": "update",
                    "message": f"测试成功: 发现 {len(new_items)} 条新通知（含被删除的记录）",
                    "new_items": new_items,
                }
            )

            if download_enabled:
                print(f"\n[{site_name}] 下载新数据页面...")
                download_new_pages(new_items, site_key)
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


def show_config():
    config = load_config()
    if not config:
        print("未找到配置文件，请先运行: python crawler.py init")
        return

    display = json.loads(json.dumps(config))
    if "email" in display and "password" in display["email"]:
        display["email"]["password"] = "******"

    print(json.dumps(display, ensure_ascii=False, indent=4))


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
            print("请选择自启动模式:")
            print("  1. 控制台模式 (显示命令行窗口)")
            print("  2. 静默模式 (不显示窗口)")
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
        elif num == 6:
            print("\n" + "-" * 40)
            setup_autostart(False)
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 7:
            print("\n" + "-" * 40)
            show_config()
            print("-" * 40)
            input("\n按回车键继续...")
        elif num == 8:
            print("\n再见！")
            break


def main():
    if "--autostart-run" in sys.argv:
        start_scheduler()
        return

    if "--autostart-run-once" in sys.argv:
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
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
