import os
import time
import requests
from bs4 import BeautifulSoup
from abc import ABC, abstractmethod
from DrissionPage import ChromiumPage, ChromiumOptions


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
        resp = requests.get(self.IFRAME_URL, headers=self.HEADERS, timeout=15)
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
        resp = requests.get(self.URL, headers=self.HEADERS, timeout=15)
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
        co.set_browser_path(edge_path)
        temp_dir = os.path.join(os.environ.get("TEMP", ""), "crawl_nhc_profile")
        os.makedirs(temp_dir, exist_ok=True)
        co.set_user_data_path(temp_dir)
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-blink-features=AutomationControlled")

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


class MeeGovGtfwSubCrawler(BaseCrawler):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    BASE_URL = "https://www.mee.gov.cn/ywgz/gtfwyhxpgl/"
    SUB_PATH: str = ""

    def crawl(self) -> list[tuple[str, str]]:
        from urllib.parse import urljoin

        url = self.BASE_URL + self.SUB_PATH
        resp = requests.get(url, headers=self.HEADERS, timeout=15)
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
]
