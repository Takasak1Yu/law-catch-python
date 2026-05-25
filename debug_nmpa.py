import os
import time
from DrissionPage import ChromiumPage, ChromiumOptions
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = 'https://www.nmpa.gov.cn/hzhp/hzhpjmtg/index.html'

edge_path = None
paths = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
for p in paths:
    if os.path.exists(p):
        edge_path = p
        break

co = ChromiumOptions()
co.set_paths(browser_path=edge_path, user_data_path=os.path.join(os.environ.get("TEMP", ""), "crawl_nmpa_debug"))
co.set_argument("--no-sandbox")
co.set_argument("--disable-blink-features=AutomationControlled")

page = ChromiumPage(co)
try:
    page.get(url)
    for _ in range(20):
        time.sleep(2)
        title = page.title
        if title and "nmpa" not in title.lower() and len(title) > 2:
            break

    html = page.html
    soup = BeautifulSoup(html, 'html.parser')

    # Find the main content list area
    # Look for common list container patterns
    for cls in ['list', 'news-list', 'content-list', 'article-list', 'text-list', 'main-list', 'data-list']:
        found = soup.find_all(class_=lambda c: c and cls in str(c).lower())
        if found:
            print(f'\nClass containing "{cls}":')
            for f in found[:3]:
                print(f'  tag={f.name} class={f.get("class")} children={len(f.find_all("a"))}')

    # Look for ul/ol in main content
    for ul in soup.find_all(['ul', 'ol']):
        links = ul.find_all('a', href=True)
        if len(links) >= 5:
            cls = ul.get('class', '')
            print(f'\nList: tag={ul.name} class={cls} links={len(links)}')
            for a in links[:3]:
                print(f'  {a.get_text(strip=True)[:60]}')
                print(f'  {a["href"][:80]}')

    # Check specific list items with dates
    print('\n--- Looking for list items with date patterns ---')
    for li in soup.find_all('li'):
        text = li.get_text(strip=True)
        links = li.find_all('a', href=True)
        if links and ('2026' in text or '2025' in text):
            cls = li.get('class', '')
            parent_cls = li.parent.get('class', '') if li.parent else ''
            print(f'  li class={cls} parent class={parent_cls}')
            for a in links:
                print(f'    {a.get_text(strip=True)[:60]}')
                print(f'    {a["href"][:80]}')

finally:
    page.quit()
