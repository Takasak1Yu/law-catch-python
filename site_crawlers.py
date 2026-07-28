import os
import time
import socket
import subprocess
import requests
import urllib3
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod
from DrissionPage import ChromiumPage, ChromiumOptions

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CRAWLER_PORTS = [9223, 9224, 9225, 9226, 9227, 9228]


def wait_for_port_free(port: int, timeout: int = 30, interval: float = 1.0):
    """等待端口释放，若端口被占用则循环检测直到超时"""
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(("127.0.0.1", port))
            if result != 0:
                return True
        time.sleep(interval)
    return False


def kill_crawler_browsers():
    """关闭所有爬虫调用的Edge浏览器进程"""
    try:
        subprocess.run(
            [
                "powershell", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                "Where-Object { $_.CommandLine -match 'crawl_|download_' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass
    time.sleep(2)


class BaseCrawler(ABC):
    site_key: str = ""
    site_name: str = ""

    @abstractmethod
    def crawl(self) -> list[tuple[str, str]]:
        pass


class MeeGovCrawler(BaseCrawler):
    site_key = "mee_gov_wjk"
    site_name = "生态环境部文件库"

    IFRAME_URL = "https://www.mee.gov.cn/govsearch/wenjiankujs.jsp?Stype=2&type=1&orderby=date"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.mee.gov.cn/wjk/",
    }

    def crawl(self) -> list[tuple[str, str]]:
        resp = requests.get(self.IFRAME_URL, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for a_tag in soup.select("table a[href]"):
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not title:
                continue
            if href.startswith("/"):
                href = "https://www.mee.gov.cn" + href
            results.append((title, href))

        return results


class MeeGovGzkCrawler(BaseCrawler):
    site_key = "mee_gov_gzk"
    site_name = "生态环境部规则库"

    URL = "https://www.mee.gov.cn/gzk/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def crawl(self) -> list[tuple[str, str]]:
        resp = requests.get(self.URL, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if not href.endswith(".shtml"):
                continue
            if href.startswith("./"):
                href = "https://www.mee.gov.cn/gzk/" + href[2:]
            elif href.startswith("/"):
                href = "https://www.mee.gov.cn" + href
            results.append((title, href))

        return results


class NhcGovCrawler(BaseCrawler):
    site_key = "nhc_gov_sps"
    site_name = "国家卫健委食品安全"

    URL = "https://www.nhc.gov.cn/sps/c100088/new_list.shtml"
    LINK_KEYWORD = "sps/c100088"

    def _get_edge_path(self) -> str | None:
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def crawl(self) -> list[tuple[str, str]]:
        edge_path = self._get_edge_path()
        if not edge_path:
            raise RuntimeError("未找到Edge浏览器，无法爬取国家卫健委网站")

        co = ChromiumOptions()
        co.set_paths(browser_path=edge_path, local_port=9223,
                     user_data_path=os.path.join(os.environ.get("TEMP", ""), "crawl_nhc_profile"))
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--proxy-server='direct://'")
        co.set_argument("--proxy-bypass-list=*")

        wait_for_port_free(9223)
        page = ChromiumPage(co)
        try:
            page.get(self.URL)

            for _ in range(15):
                time.sleep(2)
                title = page.title
                if title and "nhc" not in title.lower():
                    break

            results = []
            for link in page.eles("css:a"):
                try:
                    href = link.attr("href") or ""
                    text = link.text.strip()
                    if not text:
                        continue
                    if self.LINK_KEYWORD in href and href.endswith(".shtml"):
                        if text.isdigit() and len(text) <= 2:
                            continue
                        if href == self.URL:
                            continue
                        results.append((text, href))
                except Exception:
                    continue

            return results
        finally:
            page.quit()
            time.sleep(3)


class MeeGovGtfwSubCrawler(BaseCrawler):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    BASE_URL = "https://www.mee.gov.cn/ywgz/gtfwyhxpgl/"
    SUB_PATH: str = ""

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        url = self.BASE_URL + self.SUB_PATH
        resp = requests.get(url, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if not (href.endswith(".shtml") or href.endswith(".html") or href.endswith(".htm")):
                continue
            full_url = urljoin(url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append((title, full_url))

        return results


class MeeGovGtfw_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_gtfw"
    site_name = "固体废物与化学品-固体废物"
    SUB_PATH = "gtfw/"


class MeeGovWxfw_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_wxfw"
    site_name = "固体废物与化学品-危险废物"
    SUB_PATH = "wxfw/"


class MeeGovHxphjgl_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_hxphjgl"
    site_name = "固体废物与化学品-化学品环境管理"
    SUB_PATH = "hxphjgl/"


class MeeGovZjshjgl_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_zjshjgl"
    site_name = "固体废物与化学品-重金属环境管理"
    SUB_PATH = "zjshjgl/"


class MeeGovGnlygz_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_gnlygz"
    site_name = "固体废物与化学品-国内履约工作"
    SUB_PATH = "gnlygz/"


class MeeGovFqdq_Crawler(MeeGovGtfwSubCrawler):
    site_key = "mee_gov_fqdq"
    site_name = "固体废物与化学品-废弃电器电子产品审核"
    SUB_PATH = "fqdqdzcpcjclqksh/"


class NifdcCrawler(BaseCrawler):
    URL: str = ""
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        resp = requests.get(self.URL, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        list_div = soup.find("div", class_="list")
        if not list_div:
            return []

        results = []
        seen_urls = set()
        for a_tag in list_div.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if not (href.endswith(".html") or href.endswith(".htm") or href.endswith(".shtml")):
                continue
            full_url = urljoin(self.URL, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append((title, full_url))

        return results


class NifdcZcfgCrawler(NifdcCrawler):
    site_key = "nifdc_zcfg"
    site_name = "中检院法规政策"
    URL = "https://www.nifdc.org.cn/nifdc/xxgk/zcfg/index.html"


class NifdcGgtzhCrawler(NifdcCrawler):
    site_key = "nifdc_ggtzh"
    site_name = "中检院公告通知"
    URL = "https://www.nifdc.org.cn/nifdc/xxgk/ggtzh/index.html"


class NmpaCrawler(BaseCrawler):
    URL: str = ""

    def _get_edge_path(self) -> str | None:
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        edge_path = self._get_edge_path()
        if not edge_path:
            raise RuntimeError("未找到Edge浏览器，无法爬取国家药监局网站")

        co = ChromiumOptions()
        co.set_paths(browser_path=edge_path, local_port=9224,
                     user_data_path=os.path.join(os.environ.get("TEMP", ""), "crawl_nmpa_profile"))
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--proxy-server='direct://'")
        co.set_argument("--proxy-bypass-list=*")

        wait_for_port_free(9224)
        page = ChromiumPage(co)
        try:
            page.get(self.URL)

            for _ in range(20):
                time.sleep(2)
                title = page.title
                if title and "nmpa" not in title.lower() and len(title) > 2:
                    break

            html = page.html
            soup = BeautifulSoup(html, "html.parser")

            list_div = soup.find("div", class_="list")
            if not list_div:
                list_div = soup.find("div", class_="yp-child-list")
            if not list_div:
                return []

            results = []
            seen = set()
            for a_tag in list_div.find_all("a", href=True):
                href = a_tag["href"]
                title = a_tag.get_text(strip=True)
                if not title or not href:
                    continue
                if not (href.endswith(".html") or href.endswith(".htm")):
                    continue
                full_url = urljoin(self.URL, href)
                if full_url in seen:
                    continue
                seen.add(full_url)
                results.append((title, full_url))

            return results
        finally:
            page.quit()
            time.sleep(3)


class NmpaHzhpjmtgCrawler(NmpaCrawler):
    site_key = "nmpa_hzhpjmtg"
    site_name = "国家药监局化妆品公告通告"
    URL = "https://www.nmpa.gov.cn/hzhp/hzhpjmtg/index.html"


class NmpaHzhpfgwjCrawler(NmpaCrawler):
    site_key = "nmpa_hzhpfgwj"
    site_name = "国家药监局化妆品法规文件"
    URL = "https://www.nmpa.gov.cn/hzhp/hzhpfgwj/index.html"


class NmpaXxgkFgwjCrawler(NmpaCrawler):
    site_key = "nmpa_xxgk_fgwj"
    site_name = "国家药监局法规文件"
    URL = "https://www.nmpa.gov.cn/xxgk/fgwj/index.html"


class CustomsGovCrawler(BaseCrawler):
    site_key = "customs_gov_hgfg"
    site_name = "海关总署海关法规"

    URL = "http://www.customs.gov.cn/customs/302249/302266/index.html"
    LINK_KEYWORD = "/article_"

    def _get_edge_path(self) -> str | None:
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        edge_path = self._get_edge_path()
        if not edge_path:
            raise RuntimeError("未找到Edge浏览器，无法爬取海关总署网站")

        co = ChromiumOptions()
        co.set_paths(browser_path=edge_path, local_port=9225,
                     user_data_path=os.path.join(os.environ.get("TEMP", ""), "crawl_customs_profile"))
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--proxy-server='direct://'")
        co.set_argument("--proxy-bypass-list=*")

        wait_for_port_free(9225)
        page = ChromiumPage(co)
        try:
            page.get(self.URL)

            for _ in range(20):
                time.sleep(2)
                title = page.title
                if title and title != self.URL and len(title) > 2:
                    break

            results = []
            seen = set()
            for link in page.eles("css:a"):
                try:
                    href = link.attr("href") or ""
                    text = link.text.strip()
                    if not text or not href:
                        continue
                    if not href.endswith(".html"):
                        continue
                    if text.isdigit() and len(text) <= 2:
                        continue
                    if href == self.URL:
                        continue
                    if self.LINK_KEYWORD not in href:
                        continue
                    full_url = urljoin(self.URL, href)
                    if full_url in seen:
                        continue
                    seen.add(full_url)
                    results.append((text, full_url))
                except Exception:
                    continue

            return results
        finally:
            page.quit()
            time.sleep(3)


class ShMsaCrawler(BaseCrawler):
    site_key = "sh_msa_hsfg"
    site_name = "上海海事局海事法规"

    URL = "https://www.sh.msa.gov.cn/hsfg/list.jspx"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        resp = requests.get(self.URL, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if "content.jspx" not in href:
                continue
            full_url = urljoin(self.URL, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append((title, full_url))

        return results


class MemGovCrawler(BaseCrawler):
    site_key = "mem_gov_fg"
    site_name = "应急管理部法律法规"

    URL = "https://www.mem.gov.cn/fw/flfgbz/fg/"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        resp = requests.get(self.URL, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if href.startswith("#") or href.startswith("javascript"):
                continue
            if not (".shtml" in href or ".html" in href or ".htm" in href
                    or "flk.npc.gov.cn" in href or ".pdf" in href):
                continue
            full_url = urljoin(self.URL, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append((title, full_url))

        return results


class MemGovFdzdgkCrawler(BaseCrawler):
    site_key = "mem_gov_fdzdgk"
    site_name = "应急管理部政府信息公开"

    URL = "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/"
    IFRAME_SRC = "https://www.mem.gov.cn/gk/zfxxgkpt/fdzdgknr/46/index_1771.shtml"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        resp = requests.get(self.IFRAME_SRC, headers=self.HEADERS, timeout=15, verify=False)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        seen_urls = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            title = a_tag.get_text(strip=True)
            if not title:
                continue
            if href.startswith("#") or href.startswith("javascript"):
                continue
            if not (".shtml" in href or ".html" in href or ".htm" in href
                    or "flk.npc.gov.cn" in href or ".pdf" in href):
                continue
            full_url = urljoin(self.IFRAME_SRC, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append((title, full_url))

        return results


class MiitCrawler(BaseCrawler):
    URL: str = ""
    LINK_KEYWORD = "art_"

    def _get_edge_path(self) -> str | None:
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return None

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        edge_path = self._get_edge_path()
        if not edge_path:
            raise RuntimeError("未找到Edge浏览器，无法爬取工信部网站")

        co = ChromiumOptions()
        co.set_paths(browser_path=edge_path, local_port=9226,
                     user_data_path=os.path.join(os.environ.get("TEMP", ""), "crawl_miit_profile"))
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--proxy-server='direct://'")
        co.set_argument("--proxy-bypass-list=*")

        wait_for_port_free(9226)
        page = ChromiumPage(co)
        try:
            page.get(self.URL)

            for _ in range(15):
                time.sleep(2)
                html = page.html
                if len(html) > 5000:
                    break

            soup = BeautifulSoup(html, "html.parser")

            results = []
            seen = set()
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                title = a_tag.get_text(strip=True)
                if not title or not href:
                    continue
                if self.LINK_KEYWORD not in href:
                    continue
                if not (".html" in href or ".shtml" in href or ".htm" in href):
                    continue
                if len(title) <= 5:
                    continue
                full_url = urljoin(self.URL, href)
                if full_url in seen:
                    continue
                seen.add(full_url)
                results.append((title, full_url))

            return results
        finally:
            page.quit()
            time.sleep(3)


class MiitZcwjkCrawler(MiitCrawler):
    site_key = "miit_zcwjk"
    site_name = "工信部政策文件库"
    URL = "https://www.miit.gov.cn/search/zcwjk.html?websiteid=110000000000000&pg=&p=&tpl=14&category=183&q="


class MiitFlfgCrawler(MiitCrawler):
    site_key = "miit_flfg"
    site_name = "工信部法律法规"
    URL = "https://www.miit.gov.cn/zwgk/zcwj/flfg/index.html"


class MiitBmgzkCrawler(MiitCrawler):
    site_key = "miit_bmgzk"
    site_name = "工信部部门规章库"
    URL = "https://www.miit.gov.cn/search/bmgzk.html?websiteid=110000000000000&pg=&p=&tpl=14&category=181&q="


class MiitXzgfxwjCrawler(MiitCrawler):
    site_key = "miit_xzgfxwj"
    site_name = "工信部行政规范性文件"
    URL = "https://www.miit.gov.cn/search/zcwjk.html?websiteid=110000000000000&pg=&p=&tpl=14&category=46&q="


class MiitWjgsCrawler(MiitCrawler):
    site_key = "miit_wjgs"
    site_name = "工信部文件公示"
    URL = "https://www.miit.gov.cn/zwgk/wjgs/index.html"


class MiitHdjlCrawler(MiitCrawler):
    site_key = "miit_hdjl"
    site_name = "工信部互动交流"
    URL = "https://www.miit.gov.cn/hdjl/index.html"


ALL_CRAWLERS: list[BaseCrawler] = [
    MeeGovCrawler(),
    MeeGovGzkCrawler(),
    NhcGovCrawler(),
    MeeGovGtfw_Crawler(),
    MeeGovWxfw_Crawler(),
    MeeGovHxphjgl_Crawler(),
    MeeGovZjshjgl_Crawler(),
    MeeGovGnlygz_Crawler(),
    MeeGovFqdq_Crawler(),
    NifdcZcfgCrawler(),
    NifdcGgtzhCrawler(),
    NmpaHzhpjmtgCrawler(),
    NmpaHzhpfgwjCrawler(),
    NmpaXxgkFgwjCrawler(),
    CustomsGovCrawler(),
    ShMsaCrawler(),
    MemGovCrawler(),
    MemGovFdzdgkCrawler(),
    MiitZcwjkCrawler(),
    MiitFlfgCrawler(),
    MiitBmgzkCrawler(),
    MiitXzgfxwjCrawler(),
    MiitWjgsCrawler(),
    MiitHdjlCrawler(),
]
