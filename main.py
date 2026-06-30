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

# 国交省のJavaScript対策として、報道発表のバックアップURLおよびRSSを組み込み
TARGET_SITES = {
    "総務省": "https://www.soumu.go.jp/menu_news/s-news/jinji.html",
    "消防庁": "https://www.fdma.go.jp/pressrelease/jinji/",
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/kanbou/jidou/",
    "国土交通省(報道発表経由)": "https://www.mlit.go.jp/report/press/index.html", # JS回避用バックアップ
    "農林水産省": "https://www.maff.go.jp/j/press/jinji/",
    "水産庁": "https://www.jfa.maff.go.jp/j/press/jinji/",
    "厚生労働省": "https://www.mhlw.go.jp/kouseiroudoushou/shozaichi/jinji/",
    "内閣府": "https://www.cao.go.jp/jinji/jinji-shoukai.html",
    "こども家庭庁": "https://www.cfa.go.jp/pressrelease/",
    "文部科学省": "https://www.mext.go.jp/b_menu/shingi/jinji/index.htm",
    "復興庁": "https://www.reconstruction.go.jp/topics/main-cat2/sub-cat2-5/",
    "経済産業省": "https://www.meti.go.jp/annai/saiyou/jinji/index.html",
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
    return re.sub(r'\s+', '', text)

def is_member_in_pdf(cleaned_name, raw_pdf_text, cleaned_pdf_text):
    if cleaned_name in cleaned_pdf_text:
        return True
    chars = [c for c in cleaned_name if c.strip()]
    if len(chars) < 2: return False
    
    if all(c in cleaned_pdf_text for c in chars):
        first_char = chars[0]
        for match in re.finditer(re.escape(first_char), raw_pdf_text):
            start_pos = max(0, match.start() - 150)
            end_pos = min(len(raw_pdf_text), match.end() + 150)
            surrounding_text = raw_pdf_text[start_pos:end_pos]
            if all(c in surrounding_text for c in chars):
                return True
    return False

def check_ministries():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for site_name, url in TARGET_SITES.items():
        print(f"【巡回中】{site_name} をチェックしています...")
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 各ページ内のリンクを抽出
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                # 人事異動に関係しそうなPDF、または通常リンクを網羅
                if href.endswith('.pdf') or 'jidou' in href or 'jinji' in href or 'kanpou' in url:
                    if href.startswith('http'): target_url = href
                    elif href.startswith('/'):
                        from urllib.parse import urlparse
                        parsed_url = urlparse(url)
                        target_url = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
                    else: target_url = url.rstrip('/') + '/' + href.lstrip('/')
                    if target_url not in links:
                        links.append(target_url)

            # 抽出した各URLの精査
            for target_url in links:
                if not (target_url.endswith('.pdf') or 'kanpou.npb.go.jp' in target_url):
                    continue # 最終ターゲットがPDFまたは官報HTML以外はスキップ
                    
                try:
                    res = requests.get(target_url, headers=headers, timeout=20)
                    if res.status_code != 200: continue
                        
                    raw_text = ""
                    is_image_pdf = False
                    
                    if target_url.endswith('.pdf'):
                        with pdfplumber.open(io.BytesIO(res.content)) as pdf:
                            raw_text = "".join([page.extract_text(layout=True) or "" for page in pdf.pages])
                        
                        # 画像PDF判定（ファイルサイズが大きいのにテキストが全く抽出できない場合）
                        if len(res.content) > 50000 and len(raw_text.strip()) < 10:
                            is_image_pdf = True
                    else:
                        html_soup = BeautifulSoup(res.text, 'html.parser')
                        raw_text = html_soup.get_text()
                    
                    cleaned_pdf_text = clean_text(raw_text)
                    hit_members = []
                    mail_type = "【人事異動検知】"
                    
                    # 1. 通常の文字マッチング
                    if not is_image_pdf:
                        for member in WATCH_DATA:
                            cleaned_name = clean_text(member["name"])
                            if not cleaned_name: continue
                                
                            if is_member_in_pdf(cleaned_name, raw_text, cleaned_pdf_text):
                                hit_info = f"{member['name']}（現想定所属: {member['agency']} / 備考: {member['memo']}）"
                                if hit_info not in hit_members:
                                    hit_members.append(hit_info)
                                    mail_type = member["type"]
                    
                    # 2. 【超重要】画像PDFだった場合のセーフティネットアラート
                    # テキストが読めない人事PDFが本日更新されていたら、見落とし防止のため強制的に通知する
                    if is_image_pdf and ("jidou" in target_url or "jinji" in target_url or "report/press" in target_url):
                        subject = f"【要手動確認・画像PDF検出】{site_name}"
                        body = (
                            f"※警告: 文字情報が抽出できない「画像化されたPDF」を検出しました。\n"
                            f"高橋さん等の該当者が含まれている可能性があるため、手動でご確認ください。\n\n"
                            f"■ 発信元サイト: {site_name}\n"
                            f"■ 対象PDFリンク: {target_url}\n"
                        )
                        send_email(subject, body)
                        continue

                    # 該当者が通常マッチした場合のメール送信
                    if hit_members:
                        subject = f"{mail_type}{site_name}"
                        body = (
                            f"以下の人物に関する人事異動情報を検知しました。\n\n"
                            f"■ 発信元サイト: {site_name}\n"
                            f"■ 該当者:\n" + "\n".join([f"  ・ {m}" for m in hit_members]) + "\n"
                            f"■ 掲載リンク: {target_url}\n\n"
                            f"※このメールは自動監視エージェントから送信されています。"
                        )
                        send_email(subject, body)
                            
                except Exception as file_error:
                    continue
            time.sleep(1)
                        
        except Exception as e:
            print(f"【エラー】{site_name}のチェック中にエラー: {e}")

if __name__ == "__main__":
    check_ministries()
