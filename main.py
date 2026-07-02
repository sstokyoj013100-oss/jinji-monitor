import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup
import pdfplumber
import io
import smtplib
import re
import csv
from email.mime.text import MIMEText
from email.utils import formatdate
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin

# ================= 1. 監視対象名簿データの構築 =================
CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', '', str(text))

def load_watch_data():
    combined_data = []
    try:
        with open(CSV_EX_OFFICIALS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name,
                    "key_name": clean_text(name),
                    "agency": row.get("agency", "").strip() or row.get("省庁", "不明"),
                    "memo": f"元下関市: {row.get('shimonoseki_title', '').strip() or row.get('元下関役職', 'データなし')}",
                    "type": "【元幹部職員の異動検知】"
                })
    except Exception as e: print(f"CSVエラー1: {e}")

    try:
        with open(CSV_IMPORTANT_POSITIONS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("希望先氏名", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                dept = row.get("要望先局等", "").strip() or row.get("要望先部署", "").strip()
                title = row.get("希望先役職", "").strip()
                combined_data.append({
                    "name": name,
                    "key_name": clean_text(name),
                    "agency": row.get("省庁", "不明").strip(),
                    "memo": f"重要ポジション（前職想定: {dept} {title}）",
                    "type": "【要監視重要ポジションの異動検知】"
                })
    except Exception as e: print(f"CSVエラー2: {e}")
    return combined_data

WATCH_DATA = load_watch_data()

# ================= 2. 送信設定・ターゲットURL =================
TO_ADDRESS_DETECT = "sstokyoj@city.shimonoseki.yamaguchi.jp"
TO_ADDRESS_REPORT = "miura.daijirou@city.shimonoseki.yamaguchi.jp"
FROM_ADDRESS = "sstokyoj013100@gmail.com"

GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "qdfy qhwd bssx ptca")

TARGET_SITES = {
    "総務省(人事・組織)": "https://www.soumu.go.jp/menu_sosiki/annai/soshiki/jinji/index.html",
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/R8jinji.html",
    "農林水産省(人事異動)": "https://www.maff.go.jp/j/org/who/meibo/personnel_change/index.html",
    "厚生労働省(幹部名簿・人事)": "https://www.mhlw.go.jp/kouseiroudoushou/kanbumeibo/index.html",
    "内閣府(幹部名簿)": "https://www.cao.go.jp/about/meibo.html",
    "こども家庭庁(人事)": "https://www.cfa.go.jp/about/jinji",
    "文部科学省(幹部名簿)": "https://www.mext.go.jp/b_menu/soshiki2/kanbumeibo.htm",
    "復興庁(人事)": "https://www.reconstruction.go.jp/topics/cat-114/jinji/",
    "経済産業省(幹部名簿PDF)": "https://www.meti.go.jp/intro/data/pdf/list_ja.pdf",
    "時事公報(人事ニュース)": "https://www.jihyo.co.jp/jinji_news/",
    "インターネット官報": "https://kanpou.npb.go.jp/"
}

# ================= 3. 通信・メール・解析の最適化関数 =================
def create_retry_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def send_emails_batch(email_tasks):
    if not email_tasks: return
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as smtpobj:
            smtpobj.starttls()
            smtpobj.login(FROM_ADDRESS, GMAIL_APP_PASSWORD)
            for subject, body, to_address in email_tasks:
                msg = MIMEText(body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = FROM_ADDRESS
                msg["To"] = to_address
                msg["Date"] = formatdate(localtime=True)
                smtpobj.sendmail(FROM_ADDRESS, [to_address], msg.as_string())
                print(f"メール送信成功: {subject} -> {to_address}")
    except Exception as e:
        print(f"メールバッチ送信失敗: {e}")

def parse_pdf_date(date_str):
    if not date_str: return None
    clean_str = date_str.replace("D:", "").replace("'", "").replace("Z", "")
    
    match = re.match(r'^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?', clean_str)
    if match:
        try:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            hour = int(match.group(4)) if match.group(4) else 0
            minute = int(match.group(5)) if match.group(5) else 0
            second = int(match.group(6)) if match.group(6) else 0
            return datetime(year, month, day, hour, minute, second)
        except (ValueError, IndexError):
            return None
    return None

def extract_vertical_text_from_page(page):
    words = page.extract_words()
    if not words: return ""
    words_sorted = sorted(words, key=lambda w: (-round(w['x0'] / 15), w['top']))
    return "".join([w['text'] for w in words_sorted])

def get_surrounding_context_html(name, raw_text, site_name=""):
    """ HTML用の周辺テキスト抽出 """
    cleaned_raw = re.sub(r'\s+', ' ', raw_text)
    pattern = ".*".join([re.escape(c) for c in name if c.strip()])
    match = re.search(pattern, cleaned_raw)
    if match:
        width = 25 if "厚生労働省" in site_name else 60
        start = max(0, match.start() - width)
        end = min(len(cleaned_raw), match.end() + width)
        context = cleaned_raw[start:end].strip()
        return f"... {context} ..."
    return "周辺情報の取得失敗"

def get_surrounding_context_by_line(page, member_name):
    """ PDF用：氏名と同じ行（同じ高さ）にあるテキストだけを横一列で抽出 """
    words = page.extract_words()
    if not words: return "周辺情報の取得失敗"
    
    cleaned_target = clean_text(member_name)
    full_text = "".join([w['text'] for w in words])
    if cleaned_target not in clean_text(full_text):
        return "ターゲットが見つかりません"
        
    first_char = member_name[0]
    target_words = [w for w in words if first_char in w['text']]
    
    if not target_words:
        return "周辺情報の取得失敗(行特定不可)"
        
    base_word = target_words[0]
    base_top = base_word['top']
    base_bottom = base_word['bottom']
    
    tolerance = 5 
    
    same_line_words = [
        w for w in words 
        if (base_top - tolerance) <= w['top'] <= (base_bottom + tolerance)
    ]
    
    same_line_words_sorted = sorted(same_line_words, key=lambda w: w['x0'])
    line_text = " ".join([w['text'] for w in same_line_words_sorted])
    
    return line_text if line_text.strip() else "周辺情報の取得失敗"

def is_member_in_text(cleaned_name, raw_text, cleaned_text_data):
    if cleaned_name in cleaned_text_data:
        return True
    chars = [c for c in cleaned_name if c.strip()]
    if len(chars) < 2: return False
    
    first_char = chars[0]
    for match in re.finditer(re.escape(first_char), raw_text):
        start_pos = match.start()
        end_pos = min(len(raw_text), start_pos + 200)
        surrounding_text = raw_text[start_pos:end_pos]
        cleaned_surrounding = clean_text(surrounding_text)
        
        if cleaned_name in cleaned_surrounding:
            return True
        regex_pattern = ".*".join([re.escape(c) for c in chars])
        if re.search(regex_pattern, surrounding_text):
            return True
    return False

def collect_links_from_url(session, url, headers, deep_crawl=False):
    if url.endswith('.pdf'):
        return [url]
        
    links = []
    try:
        res = session.get(url, headers=headers, timeout=40)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            target_url = urljoin(url, href)
            
            if href.endswith('.pdf') or href.endswith('.html') or href.endswith('.htm') or 'jidou' in href or 'jinji' in href or 'meibo' in href or 'kanpou' in url:
                if target_url not in links:
                    links.append(target_url)
                    
        if deep_crawl:
            sub_links = []
            for l in links:
                if (l.endswith('.html') or l.endswith('.htm')) and ('jinji' in l or 'sosiki' in l or 'meibo' in l or 'saiyou' in l or 'b_menu' in l or 'intro' in l):
                    try:
                        time.sleep(0.5)
                        sub_res = session.get(l, headers=headers, timeout=40)
                        sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
                        for sub_a in sub_soup.find_all('a', href=True):
                            sub_href = sub_a['href'].strip()
                            sub_target = urljoin(l, sub_href)
                            if sub_target.endswith('.pdf') and sub_target not in links and sub_target not in sub_links:
                                sub_links.append(sub_target)
                    except:
                        continue
            links.extend(sub_links)
            
    except Exception as e:
        print(f"リンク収集エラー ({url}): {e}")
    return links

def build_grouped_email_body(hits_dict):
    body = ""
    for key_name in sorted(hits_dict.keys()):
        info = hits_dict[key_name]
        is_recent_24h = any(src.get('recent_24h', False) for src in info['sources'])
        flash_label = " 【★超速報: 24時間以内の新着情報】" if is_recent_24h else ""
        
        body += f"■ 氏名: {info['display_name']}{flash_label}\n"
        body += f"  ・ 現想定所属: {info['agency']}\n"
        body += f"  ・ 備考: {info['memo']}\n"
        body += f"  ・ 検知ソース:\n"
        
        for i, src in enumerate(info['sources'], 1):
            time_info = " (24h以内新着)" if src.get('recent_24h', False) else ""
            body += f"    [{i}] 発信元: {src['site_name']} ({src['page']}){time_info}\n"
            body += f"        新所属(周辺テキスト): {src['new_position']}\n"
            body += f"        掲載リンク: {src['url']}\n"
        body += "\n"
    return body

# ================= 4. メイン監視処理 =================
def check_ministries():
    headers = {
