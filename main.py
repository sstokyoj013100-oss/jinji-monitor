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
import json
from email.mime.text import MIMEText
from email.utils import formatdate
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin

# ================= 1. 監視対象名簿データの構築 =================
CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"
HISTORY_FILE = "detection_history.json"  # 過去の検知履歴を保存するファイル

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

# ================= 履歴管理用関数 =================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 最低限のバリデーション
                if isinstance(data, dict) and "hits" in data and "warnings" in data:
                    return data
        except Exception as e:
            print(f"履歴ファイルの読み込みに失敗しました(新規作成します): {e}")
    return {"hits": [], "warnings": []}

def save_history(history_data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
        print("検知履歴をローカルに保存しました。")
    except Exception as e:
        print(f"履歴ファイルの保存に失敗しました: {e}")

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
    "時事公報(人事ニュース)": "https://www.jihyo.co.jp/jinji_news/",
    "インターネット官報": "https://kanpou.npb.go.jp/"
}

# ================= 3. 通信・メール・解析の最適化関数 =================
def create_retry_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
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

def get_surrounding_context_html_v2(name, html_lines):
    pattern = ".*".join([re.escape(c) for c in name if c.strip()])
    for line in html_lines:
        cleaned_line = re.sub(r'\s+', ' ', line).strip()
        if not cleaned_line: continue
        
        match = re.search(pattern, clean_text(cleaned_line))
        if match or (clean_text(name) in clean_text(cleaned_line)):
            if len(cleaned_line) <= 150:
                return f"... {cleaned_line} ..."
            
            actual_match = re.search(".*".join([re.escape(c) for c in name if c.strip()]), cleaned_line)
            if actual_match:
                start = max(0, actual_match.start() - 20)
                end = min(len(cleaned_line), actual_match.end() + 100)
                return f"... {cleaned_line[start:end].strip()} ..."
            return f"... {cleaned_line[:150].strip()} ..."
            
    return "周辺情報の取得失敗"

def get_surrounding_context_by_line(page, member_name):
    words = page.extract_words()
    if not words: return "周辺情報の取得失敗"
    cleaned_target = clean_text(member_name)
    full_text = "".join([w['text'] for w in words])
    if cleaned_target not in clean_text(full_text):
        return "ターゲットが見つかりません"
        
    first_char = member_name[0]
    target_words = [w for w in words if first_char in w['text']]
    if not target_words: return "周辺情報の取得失敗(行特定不可)"
        
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
    cleaned_line = re.sub(r'\s+', ' ', line_text).strip()
    
    pattern = ".*".join([re.escape(c) for c in member_name if c.strip()])
    match = re.search(pattern, cleaned_line)
    if match:
        start = max(0, match.start() - 20)
        end = len(cleaned_line)
        return f"... {cleaned_line[start:end].strip()}"
        
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

def clean_and_validate_url(base_url, href_str):
    href_str = href_str.strip()
    if not href_str or href_str.startswith(('javascript:', 'mailto:', '#')):
        return None

    if "https:/" in href_str[6:] or "http:/" in href_str[5:]:
        matches = re.findall(r'https?://[^\s]+', href_str)
        if matches:
            target_url = matches[-1]
        else:
            return None
    else:
        target_url = urljoin(base_url, href_str)

    parsed_target = urlparse(target_url)
    host = parsed_target.netloc.lower()

    allowed_domains = [
        "soumu.go.jp", "mlit.go.jp", "maff.go.jp", "mhlw.go.jp", 
        "cao.go.jp", "cfa.go.jp", "mext.go.jp", "reconstruction.go.jp", 
        "meti.go.jp", "jihyo.co.jp", "kanpou.npb.go.jp"
    ]

    is_valid_domain = any(host == domain or host.endswith("." + domain) for domain in allowed_domains)

    if is_valid_domain and parsed_target.scheme in ['http', 'https']:
        return target_url
        
    return None

def collect_links_from_url(session, url, headers, deep_crawl=False):
    if url.endswith('.pdf'):
        return [url]
        
    links = []
    try:
        res = session.get(url, headers=headers, timeout=20)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            target_url = clean_and_validate_url(url, href)
            if not target_url: continue
            
            if href.endswith('.pdf') or href.endswith('.html') or href.endswith('.htm') or 'jidou' in href or 'jinji' in href or 'meibo' in href or 'kanpou' in url:
                if target_url not in links:
                    links.append(target_url)
                    
        if deep_crawl:
            sub_links = []
            for l in links:
                if (l.endswith('.html') or l.endswith('.htm')) and ('jinji' in l or 'sosiki' in l or 'meibo' in l or 'saiyou' in l or 'b_menu' in l or 'intro' in l):
                    try:
                        time.sleep(0.5)
                        sub_res = session.get(l, headers=headers, timeout=20)
                        sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
                        for sub_a in sub_soup.find_all('a', href=True):
                            sub_href = sub_a['href'].strip()
                            sub_target = clean_and_validate_url(l, sub_href)
                            if sub_target and sub_target.endswith('.pdf') and sub_target not in links and sub_target not in sub_links:
                                sub_links.append(sub_target)
                    except:
                        continue
            links.extend(sub_links)
            
    except Exception as e:
        print(f"リンク収集エラー ({url}): {e}")
    return links

def download_file_safely(session, url, headers):
    try:
        is_meti = "meti.go.jp" in url
        is_meti_pdf = is_meti and url.endswith(".pdf")
        
        current_headers = headers.copy()
        if is_meti:
            current_headers["Referer"] = "https://www.meti.go.jp/"
            if is_meti_pdf:
                current_headers["Accept"] = "application/pdf,*/*"
        
        connect_timeout = 180 if is_meti_pdf else 20
        download_limit_time = 180 if is_meti_pdf else 20
        
        with session.get(url, headers=current_headers, timeout=connect_timeout, stream=True) as res:
            res.raise_for_status()
            
            content_type = res.headers.get("Content-Type", "")
            if is_meti_pdf and "pdf" not in content_type.lower():
                print(f"警告: PDFを期待しましたが異なるファイル型が返されました ({content_type}) -> URL: {url}")
                return None
                
            content = bytearray()
            start_time = time.time()
            
            for chunk in res.iter_content(chunk_size=524288): 
                if time.time() - start_time > download_limit_time:
                    print(f"警告: 設定された制限時間({download_limit_time}秒)以内にダウンロードが終わらないため切断しました ({url})")
                    return None
                if chunk:
                    content.extend(chunk)
                
                size_limit = 52428800 if is_meti_pdf else 31457280
                if len(content) > size_limit:
                    print(f"警告: ファイルサイズが大きすぎるためスキップします ({url})")
                    return None
                    
            return bytes(content)
    except Exception as e:
        print(f"ダウンロードエラー ({url}): {e}")
        return None

def build_grouped_email_body_v2(hits_dict, history_keys):
    new_hits_body = ""
    old_hits_body = ""
    
    for key_name in sorted(hits_dict.keys()):
        info = hits_dict[key_name]
        new_sources = []
        old_sources = []
        
        for src in info['sources']:
            history_key = f"{key_name}_{src['url']}_{src['page']}"
            if history_key in history_keys:
                old_sources.append(src)
            else:
                new_sources.append(src)
        
        if new_sources:
            is_recent_24h = any(s.get('recent_24h', False) for s in new_sources)
            flash_label = " 【★超速報: 24時間以内の新着情報】" if is_recent_24h else ""
            
            new_hits_body += f"■ 氏名: {info['display_name']}{flash_label}\n"
            new_hits_body += f"  ・ 現想定所属: {info['agency']}\n"
            new_hits_body += f"  ・ 備考: {info['memo']}\n"
            new_hits_body += f"  ・ 検知ソース:\n"
            for i, src in enumerate(new_sources, 1):
                time_info = " (24h以内新着)" if src.get('recent_24h', False) else ""
                new_hits_body += f"    [{i}] 発信元: {src['site_name']} ({src['page']}){time_info}\n"
                new_hits_body += f"        新所属(周辺テキスト): {src['new_position']}\n"
                new_hits_body += f"        掲載リンク: {src['url']}\n"
            new_hits_body += "\n"
            
        if old_sources:
            old_hits_body += f"■ 氏名: {info['display_name']} (前回以前から継続掲載中)\n"
            old_hits_body += f"  ・ 現想定所属: {info['agency']}\n"
            old_hits_body += f"  ・ 備考: {info['memo']}\n"
            old_hits_body += f"  ・ 検知ソース:\n"
            for i, src in enumerate(old_sources, 1):
                old_hits_body += f"    [{i}] 発信元: {src['site_name']} ({src['page']})\n"
                old_hits_body += f"        新所属(周辺テキスト): {src['new_position']}\n"
                old_hits_body += f"        掲載リンク: {src['url']}\n"
            old_hits_body += "\n"
            
    final_body = ""
    if new_hits_body:
        final_body += "========================================\n"
        final_body += "【新着情報（前日からの差分項目）】\n"
        final_body += "========================================\n"
        final_body += new_hits_body
        
    if old_hits_body:
        final_body += "========================================\n"
        final_body += "【過去の検知履歴（参考・継続掲載分）】\n"
        final_body += "========================================\n"
        final_body += old_hits_body
        
    return final_body, bool(new_hits_body)

# ================= 4. メイン監視処理 =================
def check_ministries():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive"
    }
    
    now = datetime.now()
    thirty_days_ago = now - timedelta(days=30)
    twenty_four_hours_ago = now - timedelta(hours=24)
    
    session = create_retry_session()
    
    # 履歴データの安全な読み込み
    history_data = load_history()
    history_hits_set = set(history_data.get("hits", []))
    history_warnings_set = set(history_data.get("warnings", []))
    
    overall_results = {}
    ex_officials_hits = {}        
    important_positions_hits = {} 
    image_pdf_warnings = []     
    email_tasks = []
    
    current_hits_keys = []
    current_warnings_urls = []
    execution_error_occurred = False
    error_message = ""

    # メインの巡回処理（致命的なエラー対策として全体をガード）
    try:
        for site_name, url in TARGET_SITES.items():
            print(f"【巡回中】{site_name} をチェックしています...")
            overall_results[site_name] = {"status": "チェック未完了(エラーの可能性)", "has_24h_pdf": False}
            
            deep_crawl_flag = True if "総務省" in site_name or "文部科学省" in site_name else False
            
            current_headers = headers.copy()
            if "meti.go.jp" in url:
                current_headers["Referer"] = "https://www.meti.go.jp/"
                
            links = collect_links_from_url(session, url, current_headers, deep_crawl=deep_crawl_flag)

            if url not in links:
                links.insert(0, url)

            checked_count = 0
            hits_in_site = 0
            
            for target_url in links:
                if not (target_url.endswith('.pdf') or target_url.endswith('.html') or target_url.endswith('.htm') or 'kanpou.npb.go.jp' in target_url or 'jidou' in target_url or 'jinji' in target_url or 'meibo' in target_url or 'jihyo.co.jp' in target_url):
                    continue
                    
                try:
                    file_content = download_file_safely(session, target_url, headers)
                    if not file_content: continue
                    
                    pages_data = [] 
                    is_image_pdf = False
                    is_src_recent_24h = False
                    html_lines_extracted = [] 
                    
                    if target_url.endswith('.pdf'):
                        checked_count += 1
                        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                            meta = pdf.metadata or {}
                            pdf_date_str = meta.get('ModDate') or meta.get('CreationDate')
                            pdf_date = parse_pdf_date(pdf_date_str)
                            
                            is_static_meibo = "meibo" in target_url or "list_ja.pdf" in target_url or "幹部名簿" in site_name
                            
                            if pdf_date and not is_static_meibo:
                                if pdf_date < thirty_days_ago:
                                    continue
                                if pdf_date >= twenty_four_hours_ago:
                                    is_src_recent_24h = True
                                    overall_results[site_name]["has_24h_pdf"] = True
                            
                            for idx, page in enumerate(pdf.pages, 1):
                                page_raw = page.extract_text(layout=True) or ""
                                
                                if "農林水産省" in site_name or "経済産業省" in site_name or (len(page_raw.strip()) < 5 and len(pdf.pages) > 0):
                                    v_text = extract_vertical_text_from_page(page)
                                    if v_text.strip():
                                        page_raw = v_text
                                        
                                pages_data.append((str(idx), page_raw, clean_text(page_raw), page))
                            
                            total_raw_len = sum(len(p[1].strip()) for p in pages_data)
                            if len(file_content) > 50000 and total_raw_len < 10:
                                is_image_pdf = True
                    else:
                        checked_count += 1
                        html_soup = BeautifulSoup(file_content.decode('utf-8', errors='ignore'), 'html.parser')
