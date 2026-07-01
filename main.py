import requests
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
    """テキストからすべての空白・改行（全角半角含む）を完全に除去する"""
    if not text: return ""
    return re.sub(r'\s+', '', str(text)).replace(' ', '').replace(' ', '')

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
                    "key_name": clean_text(name), # スペースを完全除去した照合・統合用キー
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
                    "key_name": clean_text(name), # スペースを完全除去した照合・統合用キー
                    "agency": row.get("省庁", "不明").strip(),
                    "memo": f"重要ポジション（前職想定: {dept} {title}）",
                    "type": "【要監視重要ポジションの異動検知】"
                })
    except Exception as e: print(f"CSVエラー2: {e}")
    return combined_data

WATCH_DATA = load_watch_data()

# ================= 2. 送信設定 =================
TO_ADDRESS = "sstokyoj@city.shimonoseki.yamaguchi.jp"
FROM_ADDRESS = "sstokyoj013100@gmail.com"
GMAIL_APP_PASSWORD = "qdfy qhwd bssx ptca"

TARGET_SITES = {
    "総務省(人事・組織)": "https://www.soumu.go.jp/menu_sosiki/annai/soshiki/jinji/index.html",
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/R8jinji.html",
    "農林水産省(人事異動)": "https://www.maff.go.jp/j/org/who/meibo/personnel_change/index.html",
    "厚生労働省(幹部名簿・人事)": "https://www.mhlw.go.jp/kouseiroudoushou/kanbumeibo/index.html",
    "内閣府(幹部名簿)": "https://www.cao.go.jp/about/meibo.html",
    "こども家庭庁(人事)": "https://www.cfa.go.jp/about/jinji",
    "文部科学省(幹部名簿)": "https://www.mext.go.jp/b_menu/soshiki2/kanbumeibo.htm",
    "復興庁(人事)": "https://www.reconstruction.go.jp/topics/cat-114/jinji/",
    "経済産業省(人事・採用)": "https://www.meti.go.jp/annai/saiyou/jinji/index.html",
    "経済産業省(幹部名簿)": "https://www.meti.go.jp/intro/data/index_leaders.html", # ←新しく検証ルートに追加
    "時事公報(人事ニュース)": "https://www.jihyo.co.jp/jinji_news/",
    "インターネット官報": "https://kanpou.npb.go.jp/"
}

def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = FROM_ADDRESS
    msg["To"] = TO_ADDRESS
    msg["Date"] = formatdate(localtime=True)
    try:
        smtpobj = smtplib.SMTP("smtp.gmail.com", 587)
        smtpobj.starttls()
        smtpobj.login(FROM_ADDRESS, GMAIL_APP_PASSWORD)
        smtpobj.sendmail(FROM_ADDRESS, [TO_ADDRESS], msg.as_string())
        smtpobj.close()
        print(f"メール送信成功: {subject}")
    except Exception as e:
        print(f"メール送信失敗: {e}")

def parse_pdf_date(date_str):
    if not date_str:
        return None
    clean_str = date_str.replace("D:", "").replace("'", "").replace("Z", "")
    match = re.match(r'^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?', clean_str)
    if match:
        g = match.groups()
        year = int(g[0])
        month = int(g[1])
        day = int(g[2])
        hour = int(g[3]) if g[3] else 0
        minute = int(g[4]) if g[4] else 0
        second = int(g[5]) if g[5] else 0
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None

def extract_vertical_text_from_page(page):
    words = page.extract_words()
    if not words:
        return ""
    words_sorted = sorted(words, key=lambda w: (-round(w['x0'] / 15), w['top']))
    return "".join([w['text'] for w in words_sorted])

def get_surrounding_context(name, raw_text):
    """人名の周辺テキストを抽出する（スペース違いに対応するため、元々のマッチングロジックを工夫）"""
    # 検索用として、スペースを1つに丸めた状態にする
    cleaned_raw = re.sub(r'\s+', ' ', raw_text)
    # 苗字と名前の間に任意のスペースを許容する正規表現を作成
    pattern = ".*".join([re.escape(c) for c in name if c.strip()])
    match = re.search(pattern, cleaned_raw)
    if match:
        start = max(0, match.start() - 60)
        end = min(len(cleaned_raw), match.end() + 60)
        context = cleaned_raw[start:end].strip()
        return f"... {context} ..."
    return "周辺情報の取得失敗"

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

def collect_links_from_url(url, headers, deep_crawl=False):
    links = []
    try:
        res = requests.get(url, headers=headers, timeout=20)
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
                        sub_res = requests.get(l, headers=headers, timeout=15)
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
    # 統合されたスペースなしキーでループするが、表示は綺麗な登録名(display_name)を使う
    for key_name in sorted(hits_dict.keys()):
        info = hits_dict[key_name]
        body += f"■ 氏名: {info['display_name']}\n"
        body += f"  ・ 現想定所属: {info['agency']}\n"
        body += f"  ・ 備考: {info['memo']}\n"
        body += f"  ・ 検知ソース:\n"
        
        for i, src in enumerate(info['sources'], 1):
            body += f"    [{i}] 発信元: {src['site_name']} ({src['page']})\n"
            body += f"        新所属(周辺テキスト): {src['new_position']}\n"
            body += f"        掲載リンク: {src['url']}\n"
        body += "\n"
    return body

def check_ministries():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/536.36"
    }
    
    # ★検証期間を「6ヶ月（180日）」に短縮
    six_months_ago = datetime.now() - timedelta(days=180)
    
    overall_results = {}
    ex_officials_hits = {}       
    important_positions_hits = {} 
    image_pdf_warnings = []     
    
    for site_name, url in TARGET_SITES.items():
        print(f"【巡回中】{site_name} をチェックしています...")
        overall_results[site_name] = {"status": "チェック未完了(エラーの可能性)", "details": []}
        
        # 総務省、経産省、文科省はDeep Crawlを適用
        deep_crawl_flag = True if "総務省" in site_name or "経済産業省" in site_name or "文部科学省" in site_name else False
        links = collect_links_from_url(url, headers, deep_crawl=deep_crawl_flag)

        if url not in links:
            links.insert(0, url)

        checked_count = 0
        hits_in_site = 0
        
        for target_url in links:
            if not (target_url.endswith('.pdf') or target_url.endswith('.html') or target_url.endswith('.htm') or 'kanpou.npb.go.jp' in target_url or 'jihyo.co.jp' in target_url):
                continue
                
            try:
                res = requests.get(target_url, headers=headers, timeout=20)
                if res.status_code != 200: continue
                
                pages_data = [] 
                is_image_pdf = False
                
                if target_url.endswith('.pdf'):
                    with pdfplumber.open(io.BytesIO(res.content)) as pdf:
                        meta = pdf.metadata or {}
                        pdf_date_str = meta.get('ModDate') or meta.get('CreationDate')
                        pdf_date = parse_pdf_date(pdf_date_str)
                        
                        # ★6ヶ月より古いPDFはスキップ
                        if pdf_date and pdf_date < six_months_ago:
                            overall_results[site_name]['details'].append(f"古いPDFのためスキップ (更新日: {pdf_date.strftime('%Y-%m-%d')}): {target_url}")
                            continue
                        
                        checked_count += 1
                        for idx, page in enumerate(pdf.pages, 1):
                            page_raw = page.extract_text(layout=True) or ""
                            
                            if "農林水産省" in site_name or (len(page_raw.strip()) < 5 and len(pdf.pages) > 0):
                                v_text = extract_vertical_text_from_page(page)
                                if len(v_text.strip()) > len(page_raw.strip()):
                                    page_raw = v_text
                                    
                            pages_data.append((str(idx), page_raw, clean_text(page_raw)))
                        
                        total_raw_len = sum(len(p[1].strip()) for p in pages_data)
                        if len(res.content) > 50000 and total_raw_len < 10:
                            is_image_pdf = True
                else:
                    checked_count += 1
                    html_soup = BeautifulSoup(res.text, 'html.parser')
                    for s in html_soup(['script', 'style', 'nav', 'footer']):
                        s.decompose()
                    html_text = html_soup.get_text()
                    pages_data.append(("-", html_text, clean_text(html_text)))
                
                if not is_image_pdf:
                    for member in WATCH_DATA:
                        # 判定にはスペースなしの key_name を使用
                        cleaned_name = member["key_name"]
                        if not cleaned_name: continue
                        
                        for page_num, raw_text, cleaned_pdf_text in pages_data:
                            if is_member_in_text(cleaned_name, raw_text, cleaned_pdf_text):
                                new_position_hint = get_surrounding_context(member["name"], raw_text)
                                
                                source_detail = {
                                    "site_name": site_name,
                                    "url": target_url,
                                    "page": f"該当ページ: {page_num} ページ" if page_num != "-" else "WEBページ(HTML上に直接記載)",
                                    "new_position": new_position_hint
                                }
                                
                                target_dict = ex_officials_hits if member["type"] == "【元幹部職員の異動検知】" else important_positions_hits
                                
                                # ★スペースなしの「key_name」をキーにして人物を特定・統合
                                if cleaned_name not in target_dict:
                                    target_dict[cleaned_name] = {
                                        "display_name": member["name"], # 最初に見つかった表記をメール表示用に保持
                                        "agency": member["agency"],
                                        "memo": member["memo"],
                                        "sources": []
                                    }
                                
                                if not any(s['url'] == target_url and s['page'] == source_detail['page'] for s in target_dict[cleaned_name]['sources']):
                                    target_dict[cleaned_name]['sources'].append(source_detail)
                                    hits_in_site += 1
                
                if is_image_pdf and ("jidou" in target_url or "jinji" in target_url or "meibo" in target_url):
                    warn_info = {"site_name": site_name, "url": target_url}
                    if warn_info not in image_pdf_warnings:
                        image_pdf_warnings.append(warn_info)
                    overall_results[site_name]['details'].append(f"画像PDF検出: {target_url}")
                    continue

                if hits_in_site > 0:
                    overall_results[site_name]['details'].append(f"該当者検知情報をログに記録しました: {target_url}")
                        
            except Exception as file_error:
                continue
        
        overall_results[site_name]["status"] = "正常巡回完了"
        overall_results[site_name]["summary"] = f"検証対象数: {checked_count}件 / ヒット数: {hits_in_site}件"
        time.sleep(1)

    # ================= 3. 集約メールの送信 =================
    if ex_officials_hits:
        subject = "【元幹部職員の異動検知】人事異動集約報告"
        body = "以下の元幹部職員に関する人事異動情報を検知しました。\n\n"
        body += build_grouped_email_body(ex_officials_hits)
        body += "※このメールは自動監視エージェントから送信されています。"
        send_email(subject, body)

    if important_positions_hits:
        subject = "【要監視重要ポジションの異動検知】人事異動集約報告"
        body = "以下の重要ポジションに関する人事異動情報を検知しました。\n\n"
        body += build_grouped_email_body(important_positions_hits)
        body += "※このメールは自動監視エージェントから送信されています。"
        send_email(subject, body)

    if image_pdf_warnings:
        subject = "【要手動確認・画像PDF検出一括報告】"
        body = (
            f"※警告: 文字情報が抽出できない「画像化されたPDF」が検出されました。\n"
            f"該当者が含まれている可能性があるため、手動でご確認ください。\n\n"
        )
        for w in image_pdf_warnings:
            body += f"■ 発信元サイト: {w['site_name']}\n"
            body += f"■ 対象PDFリンク: {w['url']}\n"
            body += "----------------------------------------\n"
        send_email(subject, body)

    # ================= 4. 空振り・定期生存報告メールの送信 =================
    report_subject = "【定期報告】人事異動監視エージェント・巡回完了通知"
    report_body = "人事異動の監視プログラムが実行されました。\n各省庁の巡回結果は以下の通りです。\n\n"
    report_body += "----------------------------------------\n"
    
    for site, res in overall_results.items():
        report_body += f"■ 省庁・サイト名: {site}\n"
        report_body += f"  ステータス: {res['status']}\n"
        if "summary" in res:
            report_body += f"  処理概要: {res['summary']}\n"
        if res['details']:
            report_body += "  詳細ログ:\n" + "\n".join([f"    - {d}" for d in res['details']]) + "\n"
        report_body += "----------------------------------------\n"
        
    report_body += f"\n監視対象データ数: 計 {len(WATCH_DATA)} 名\n"
    report_body += "※このメールはプログラムが正常に動作していることを証明するために自動送信されています。"
    
    print("【報告】定期生存報告メールを送信します...")
    send_email(report_subject, report_body)

if __name__ == "__main__":
    check_ministries()
