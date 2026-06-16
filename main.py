import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import smtplib
import re
import csv
from email.mime.text import MIMEText
from email.utils import formatdate

# ================= 1. 監視対象名簿データの構築 =================
CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"

def load_watch_data():
    """2つのCSVから性質の異なる名簿を読み込み、1つの監視リストに統合する"""
    combined_data = []
    
    # ---- ① 元幹部職員リストの読み込み ----
    try:
        with open(CSV_EX_OFFICIALS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                name = row.get("name", "").strip() or row.get("氏名", "").strip()
                if not name:
                    continue
                
                combined_data.append({
                    "name": name,
                    "agency": row.get("agency", "").strip() or row.get("省庁", "不明"),
                    "memo": f"元下関市: {row.get('shimonoseki_title', '').strip() or row.get('元下関役職', 'データなし')}",
                    "type": "【元幹部職員の異動検知】"
                })
                count += 1
        print(f"「{CSV_EX_OFFICIALS}」から {count} 名を読み込みました。")
    except Exception as e:
        print(f"「{CSV_EX_OFFICIALS}」の読み込み中にエラー: {e}")

    # ---- ② 要監視重要ポジションの読み込み ----
    try:
        with open(CSV_IMPORTANT_POSITIONS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                name = row.get("希望先氏名", "").strip() or row.get("氏名", "").strip()
                if not name:
                    continue
                
                agency = row.get("省庁", "不明").strip()
                dept = row.get("要望先局等", "").strip() or row.get("要望先部署", "").strip()
                title = row.get("希望先役職", "").strip()
                position_title = f"{dept} {title}".strip()
                
                combined_data.append({
                    "name": name,
                    "agency": agency,
                    "memo": f"重要ポジション（前職想定: {position_title}）",
                    "type": "【要監視重要ポジションの異動検知】"
                })
                count += 1
        print(f"「{CSV_IMPORTANT_POSITIONS}」から {count} 名を読み込みました。")
    except Exception as e:
        print(f"「{CSV_IMPORTANT_POSITIONS}」の読み込み中にエラー: {e}")

    print(f"⇒ 総監視人数: {len(combined_data)} 名")
    return combined_data

WATCH_DATA = load_watch_data()

# ================= 2. 送信設定 =================
TO_ADDRESS = "sstokyoj@city.shimonoseki.yamaguchi.jp"
FROM_ADDRESS = "sstokyoj013100@gmail.com"
GMAIL_APP_PASSWORD = "qdfy qhwd bssx ptca"  # 16桁の暗号コード
# ===============================================

TARGET_SITES = {
    "総務省・消防庁": "https://soumu.go.jp",
    "国土交通省": "https://mlit.go.jp",
    "農林水産省・水産庁": "https://maff.go.jp",
    "厚生労働省": "https://mhlw.go.jp",
    "内閣府": "https://cao.go.jp",
    "こども家庭庁": "https://cfa.go.jp",
    "文部科学省": "https://mext.go.jp",
    "復興庁": "https://reconstruction.go.jp",
    "経産省（エネ庁・中小企業庁）": "https://meti.go.jp",
    "インターネット官報（全般）": "https://npb.go.jp"
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
        print("メール送信成功")
    except Exception as e:
        print(f"メール送信失敗: {e}")

def clean_text(text):
    return re.sub(r'\s+', '', text)

def check_ministries():
    for site_name, url in TARGET_SITES.items():
        try:
            response = requests.get(url, timeout=15)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.endswith('.pdf'):
                    if href.startswith('http'):
                        pdf_url = href
                    else:
                        pdf_url = url.rstrip('/') + '/' + href.lstrip('/')
                    
                    # PDFダウンロードとテキスト化
                    pdf_res = requests.get(pdf_url, timeout=15)
                    with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
                        pdf_text = "".join([page.extract_text() or "" for page in pdf.pages])
                    
                    cleaned_pdf_text = clean_text(pdf_text)
                    hit_members = []
                    mail_type = "【人事異動検知】"
                    
                    for member in WATCH_DATA:
                        cleaned_name = clean_text(member["name"])
                        if cleaned_name and cleaned_name in cleaned_pdf_text:
                            hit_info = f"{member['name']}（現想定所属: {member['agency']} / 備考: {member['memo']}）"
                            hit_members.append(hit_info)
                            mail_type = member["type"]
                    
                    if hit_members:
                        subject = f"{mail_type}{site_name}"
                        body = (
                            f"以下の人物に関する人事異動情報を検知しました。\n\n"
                            f"■ 発信元サイト: {site_name}\n"
                            f"■ 該当者:\n" + "\n".join([f"  ・ {m}" for m in hit_members]) + "\n"
                            f"■ 掲載PDFリンク: {pdf_url}\n\n"
                            f"※このメールは自動監視エージェントから送信されています。"
                        )
                        send_email(subject, body)
                        
        except Exception as e:
            print(f"{site_name}のチェック中にエラー: {e}")

if __name__ == "__main__":
    check_ministries()
