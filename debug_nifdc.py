import requests
from bs4 import BeautifulSoup

url = 'https://www.nifdc.org.cn/nifdc/xxgk/zcfg/index.html'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
resp = requests.get(url, headers=headers, timeout=15)
resp.encoding = resp.apparent_encoding
print('Status:', resp.status_code, 'Length:', len(resp.text))

soup = BeautifulSoup(resp.text, 'html.parser')

# Find list containers
for cls in ['list', 'news-list', 'content-list', 'article-list', 'text-list', 'main-list', 'data-list', 'info-list', 'xxgk-list']:
    found = soup.find_all(class_=lambda c: c and cls in str(c).lower())
    if found:
        print(f'\nClass containing "{cls}":')
        for f in found[:3]:
            links = f.find_all('a', href=True)
            print(f'  tag={f.name} class={f.get("class")} links={len(links)}')
            for a in links[:3]:
                print(f'    {a.get_text(strip=True)[:50]}')

# Check ul/ol with many links
for ul in soup.find_all(['ul', 'ol']):
    links = ul.find_all('a', href=True)
    if len(links) >= 5:
        cls = ul.get('class', '')
        parent_cls = ul.parent.get('class', '') if ul.parent else ''
        print(f'\nList: tag={ul.name} class={cls} parent_class={parent_cls} links={len(links)}')
        for a in links[:3]:
            print(f'  {a.get_text(strip=True)[:60]}')
            print(f'  {a["href"][:80]}')

# Check div containers with many links
for div in soup.find_all('div'):
    links = div.find_all('a', href=True)
    if 5 <= len(links) <= 30:
        cls = div.get('class', '')
        direct_links = [a for a in links if a.parent.name == 'li' or (a.parent and a.parent.parent == div)]
        if direct_links:
            print(f'\nDiv: class={cls} total_links={len(links)} direct_links={len(direct_links)}')
            for a in direct_links[:3]:
                print(f'  {a.get_text(strip=True)[:60]}')
                print(f'  {a["href"][:80]}')
