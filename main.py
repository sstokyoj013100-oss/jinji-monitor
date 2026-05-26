import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import smtplib
import re
from email.mime.text import MIMEText
from email.utils import formatdate

# ================= 1. 監視対象名簿データ =================
WATCH_DATA = [
    {"name": "河合 宏一", "agency": "内閣府"},
    {"name": "杉田 博章", "agency": "内閣府"},
    {"name": "石丸 文至", "agency": "こども家庭庁"},
    {"name": "坂本 修一", "agency": "文科省"},
    {"name": "芳田 直樹", "agency": "復興庁"},
    {"name": "米澤 朋通", "agency": "総務省"},
    {"name": "北島 洋平", "agency": "資源エネルギー庁"},
    {"name": "杉谷 郁哉", "agency": "中小企業庁"},
    {"name": "酒井 貴司", "agency": "国交省"},
    {"name": "小柳 太郎", "agency": "地方公共団体金融機構"},
    {"name": "九十九 悠太", "agency": "厚労省"},
    {"name": "長谷川 学", "agency": "厚労省"},
    {"name": "中村 真弥", "agency": "水産庁"},
    {"name": "荒 高弘", "agency": "水産庁"},
    {"name": "片山 良太", "agency": "総務省"},
    {"name": "川﨑 俊正", "agency": "国交省"},
    {"name": "神長 賢人", "agency": "総務省"},
    {"name": "松林 直邦", "agency": "総務省"},
    {"name": "野間 哲人", "agency": "総務省"},
    {"name": "入江 孝行", "agency": "消防庁"},
    {"name": "田中 翔", "agency": "国交省"},
    {"name": "時任 博之", "agency": "国交省"},
    {"name": "吉村 元吾", "agency": "国交省"},
    {"name": "平澤 良輔", "agency": "国交省"},
    {"name": "山上 直人", "agency": "国交省"},
    {"name": "石井 陽", "agency": "国交省"}
]

# ================= 2. 送信設定 =================
TO_ADDRESS = "sstokyoj@city.shimonoseki.yamaguchi.jp"
FROM_ADDRESS = "sstokyoj013100@gmail.com"
GMAIL_APP_PASSWORD = "qdfy qhwd bssx ptca"  # 16桁の暗号コード
# ===============================================

# 監視対象URL（各省庁の人事・報道発表ページ ＋ インターネット官報）
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
        smtpobj = smtplib.SMTP("://gmail.com", 587)
        smtpobj.starttls()
        smtpobj.login(FROM_ADDRESS, GMAIL_APP_PASSWORD)
        smtpobj.sendmail(FROM_ADDRESS, [TO_ADDRESS], msg.as_string())
        smtpobj.close()
        print("メール送信成功")
    except Exception as e:
        print(f"メール送信失敗: {e}")

def clean_text(text):
    """テキストから空白や改行を除去して検索しやすくする関数"""
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
                    pdf_url = href if href.startswith('http') else url.rsplit('/', 1) + '/' + href.lstrip('/')
                    
                    # PDFダウンロードとテキスト化
                    pdf_res = requests.get(pdf_url, timeout=15)
                    with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
                        pdf_text = "".join([page.extract_text() or "" for page in pdf.pages])
                    
                    cleaned_pdf_text = clean_text(pdf_text)
                    hit_members = []
                    
                    # 名簿と照合（スペースを除去した状態同士で比較）
                    for member in WATCH_DATA:
                        cleaned_name = clean_text(member["name"])
                        if cleaned_name in cleaned_pdf_text:
                            hit_members.append(f"{member['name']}（現所属: {member['agency']}）")
                    
                    if hit_members:
                        subject = f"【人事異動検知】{site_name}"
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
