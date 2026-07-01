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
from urllib.parse import urlparse, urljoin

# ================= 1. 監視対象名簿データの構築 =================
CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"

def load_watch_data():
    combined_data = []
    # ---- ① 元幹部職員リストの読み込み ----
    try:
        with open(CSV_EX_OFFICIALS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name,
                    "agency": row.get("agency", "").strip() or row.get("省庁", "不明"),
                    "memo": f"元下関市: {row.get('shimonoseki_title', '').strip() or row.get('元下関役職', 'データなし')}",
                    "type": "【元幹部職員の異動検知】"
                })
    except Exception as e: print(f"CSVエラー1: {e}")

    # ---- ② 要監視重要ポジションの読み込み ----
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

# 消防庁・水産庁を調査対象から除外
TARGET_SITES = {
    "総務省(人事・組織)": "https://www.soumu.go.jp/menu_sosiki/annai/soshiki/jinji/index.html",
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/R8jinji.html",
    "農林水産省(人事異動)": "https://www.maff.go.jp/j/org/who/meibo/personnel_change/index.html",
    "厚生労働省(幹部名簿・人事)": "https://www.mhlw.go.jp/kouseiroudoushou/kanbumeibo/index.html",
    "内閣府(幹部名簿)": "https://www.cao.go.jp/about/meibo.html",
    "こども家庭庁(人事)": "https://www.cfa.go.jp/about/jinji",
    "文部科学省(幹部名簿)": "https://www.mext.go.jp/b_menu/soshiki2/kanbumeibo.htm",
    "復興庁(人事)": "https://www.reconstruction.go.jp/topics/cat-114/jinji/",
    "経済産業省": "https://www.meti.go.jp/annai/saiyou/jinji/index.html",
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

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', '', text).replace(' ', '')

def extract_vertical_text(pdf_pages):
    """縦書きPDF対応：文字の座標（x0, top）を利用して、並び順を並び替えてテキスト化する"""
    full_text = ""
    for page in pdf_pages:
        words = page.extract_words()
        # 縦書きは右から左、上から下に読まれることが多いため、x0(右側ほど大きく、左ほど小さい)とtopでソートを試みる
        # 簡易的に、大まかな列ごとにグループ化して上から下に結合
        if not words:
            continue
        # x0の降順（右から左）、かつ同じ列ならtopの昇順（上から下）
        # ただし単純ソートだとズレるため、x座標を10px単位で丸めて列を作る
        words_sorted = sorted(words, key=lambda w: (-round(w['x0'] / 15), w['top']))
        page_text = "".join([w['text'] for w in words_sorted])
        full_text += page_text + "\n"
    return full_text

def get_surrounding_context(name, raw_text):
    """人名の周辺テキスト（新所属などのヒント）を抽出する"""
    cleaned_raw = re.sub(r'\s+', ' ', raw_text) # 改行をスペースに置換して1行にする
    match = re.search(re.escape(name), cleaned_raw)
    if match:
        start = max(0, match.start() - 60)
        end = min(len(cleaned_raw), match.end() + 60)
        context = cleaned_raw[start:end].strip()
        return f"... {context} ..."
    return "周辺情報の取得失敗"

def is_member_in_pdf(cleaned_name, raw_pdf_text, cleaned_pdf_text):
    if cleaned_name in cleaned_pdf_text:
        return True
    chars = [c for c in cleaned_name if c.strip()]
    if len(chars) < 2: return False
    
    first_char = chars[0]
    for match in re.finditer(re.escape(first_char), raw_pdf_text):
        start_pos = match.start()
        end_pos = min(len(raw_pdf_text), start_pos + 200)
        surrounding_text = raw_pdf_text[start_pos:end_pos]
        cleaned_surrounding = clean_text(surrounding_text)
        
        if cleaned_name in cleaned_surrounding:
            return True
        regex_pattern = ".*".join([re.escape(c) for c in chars])
        if re.search(regex_pattern, surrounding_text):
            return True
    return False

def collect_links_from_url(url, headers, deep_crawl=False):
    """指定したURLから検証対象のリンクを収集する（urljoinで不具合対策）"""
    links = []
    try:
        res = requests.get(url, headers=headers, timeout=20)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            # urljoinを使い、相対パス（./meibo/ や /about/）を正確な絶対URLに変換
            target_url = urljoin(url, href)
            
            # 条件に合致するリンクを収集
            if href.endswith('.pdf') or href.endswith('.html') or href.endswith('.htm') or 'jidou' in href or 'jinji' in href or 'meibo' in href or 'kanpou' in url:
                if target_url not in links:
                    links.append(target_url)
                    
        # 総務省などの「ワンクッション先の中ページ」も追跡する設定の場合
        if deep_crawl:
            sub_links = []
            for l in links:
                # htmlページかつ、人事や移動に関わりそうな中ページであればもう1階層掘る
                if (l.endswith('.html') or l.endswith('.htm')) and ('jinji' in l or 'sosiki' in l or 'meibo' in l):
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

def check_ministries():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/536.36"
    }
    
    overall_results = {}
    ex_officials_hits = []      
    important_positions_hits = [] 
    image_pdf_warnings = []     
    
    for site_name, url in TARGET_SITES.items():
        print(f"【巡回中】{site_name} をチェックしています...")
        overall_results[site_name] = {"status": "チェック未完了(エラーの可能性)", "details": []}
        
        # 総務省の場合はワンクッション先（Deep Crawl）を有効化
        deep_crawl_flag = True if "総務省" in site_name else False
        links = collect_links_from_url(url, headers, deep_crawl=deep_crawl_flag)

        pdf_checked_count = 0
        hits_in_site = 0
        
        for target_url in links:
            # 最終検証対象はPDF、官報、または時事公報
            if not (target_url.endswith('.pdf') or 'kanpou.npb.go.jp' in target_url or 'jihyo.co.jp' in target_url):
                continue
                
            try:
                res = requests.get(target_url, headers=headers, timeout=20)
                if res.status_code != 200: continue
                
                pdf_checked_count += 1
                raw_text = ""
                is_image_pdf = False
                
                if target_url.endswith('.pdf'):
                    with pdfplumber.open(io.BytesIO(res.content)) as pdf:
                        # 1. 通常のテキスト抽出
                        raw_text = "".join([page.extract_text(layout=True) or "" for page in pdf.pages])
                        
                        # 2. 農林水産省などの縦書き対策（通常抽出で文字が取れない、または農水省の場合）
                        if "農林水産省" in site_name or (len(raw_text.strip()) < 20 and len(pdf.pages) > 0):
                            v_text = extract_vertical_text(pdf.pages)
                            if len(v_text.strip()) > len(raw_text.strip()):
                                raw_text = v_text # 縦書き抽出結果を採用
                    
                    if len(res.content) > 50000 and len(raw_text.strip()) < 10:
                        is_image_pdf = True
                else:
                    html_soup = BeautifulSoup(res.text, 'html.parser')
                    raw_text = html_soup.get_text()
                
                cleaned_pdf_text = clean_text(raw_text)
                
                if not is_image_pdf:
                    for member in WATCH_DATA:
                        cleaned_name = clean_text(member["name"])
                        if not cleaned_name: continue
                            
                        if is_member_in_pdf(cleaned_name, raw_text, cleaned_pdf_text):
                            # 新しい所属のヒント（周辺テキスト）を取得
                            new_position_hint = get_surrounding_context(member["name"], raw_text)
                            
                            hit_info = {
                                "name": member["name"],
                                "site_name": site_name,
                                "agency": member["agency"],
                                "memo": member["memo"],
                                "url": target_url,
                                "new_position": new_position_hint  # 新所属情報を追加
                            }
                            
                            if member["type"] == "【元幹部職員の異動検知】":
                                if not any(h['name'] == hit_info['name'] and h['url'] == hit_info['url'] for h in ex_officials_hits):
                                    ex_officials_hits.append(hit_info)
                                    hits_in_site += 1
                            else:
                                if not any(h['name'] == hit_info['name'] and h['url'] == hit_info['url'] for h in important_positions_hits):
                                    important_positions_hits.append(hit_info)
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
        overall_results[site_name]["summary"] = f"検証PDF数: {pdf_checked_count}件 / ヒット数: {hits_in_site}件"
        time.sleep(1)

    # ================= 3. 集約メールの送信 =================
    
    # ---- ① 元幹部職員の異動検知メール ----
    if ex_officials_hits:
        ex_officials_hits.sort(key=lambda x: x["name"])
        subject = "【元幹部職員の異動検知】人事異動集約報告"
        body = "以下の元幹部職員に関する人事異動情報を検知しました。\n\n"
        for h in ex_officials_hits:
            body += f"■ 氏名: {h['name']}\n"
            body += f"  ・ 発信元: {h['site_name']}\n"
            body += f"  ・ 現想定所属: {h['agency']}\n"
            body += f"  ・ 新所属(周辺テキスト): {h['new_position']}\n"  # メールに追加
            body += f"  ・ 備考: {h['memo']}\n"
            body += f"  ・ 掲載リンク: {h['url']}\n\n"
        body += "※このメールは自動監視エージェントから送信されています。"
        send_email(subject, body)

    # ---- ② 要監視重要ポジションの異動検知メール ----
    if important_positions_hits:
        important_positions_hits.sort(key=lambda x: x["name"])
        subject = "【要監視重要ポジションの異動検知】人事異動集約報告"
        body = "以下の重要ポジションに関する人事異動情報を検知しました。\n\n"
        for h in important_positions_hits:
            body += f"■ 氏名: {h['name']}\n"
            body += f"  ・ 発信元: {h['site_name']}\n"
            body += f"  ・ 現想定所属: {h['agency']}\n"
            body += f"  ・ 新所属(周辺テキスト): {h['new_position']}\n"  # メールに追加
            body += f"  ・ 備考: {h['memo']}\n"
            body += f"  ・ 掲載リンク: {h['url']}\n\n"
        body += "※このメールは自動監視エージェントから送信されています。"
        send_email(subject, body)

    # ---- ③ 画像PDF警告メールの一括送信 ----
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
