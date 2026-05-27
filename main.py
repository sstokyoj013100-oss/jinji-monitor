import requests
from bs4 import BeautifulSoup
import pdfplumber
import io
import smtplib
import re
from email.mime.text import MIMEText
from email.utils import formatdate

# ================= 1. 監視対象名簿データ（下関時代の役職を追加） =================
WATCH_DATA = [
    {"name": "赤沼 隼一", "agency": "国交省", "shimonoseki_title": "都市整備部長（H22.4.1～H25.3.31）"},
    {"name": "荒 高弘", "agency": "水産庁", "shimonoseki_title": "農林水産振興部次長・水産課長事務取扱（H28.4～H30.3）"},
    {"name": "石井 陽", "agency": "国交省", "shimonoseki_title": "都市整備部長（H27.4～H30.3）"},
    {"name": "石丸 文至", "agency": "こども家庭庁", "shimonoseki_title": "保健部長・保健所長（R3.7.6～R5.7.31）"},
    {"name": "梅野 修一", "agency": "国交省（元）", "shimonoseki_title": "港湾局長（H21.6.25～H24.6.30）"},
    {"name": "大坂 剛", "agency": "国交省", "shimonoseki_title": "都市整備部長（H18.4.1～H20.3.31）"},
    {"name": "柿澤 満絵", "agency": "厚労省（元）", "shimonoseki_title": "こども未来部こども保健課長（H27.4.1～H29.3.31）"},
    {"name": "片山 良太", "agency": "総務省（静岡県出向）", "shimonoseki_title": "財政部長（H24.5.1～H26.3.31）"},
    {"name": "河合 宏一", "agency": "内閣府", "shimonoseki_title": "総合政策部長（H12.4.1～H14.3.31）"},
    {"name": "川﨑 俊正", "agency": "国交省", "shimonoseki_title": "港湾局長（H27.7.1～H30.2.4）"},
    {"name": "神長 賢人", "agency": "総務省", "shimonoseki_title": "財政部長（R.1.8.1～R.4.6.30）"},
    {"name": "北澤 壮介", "agency": "民間", "shimonoseki_title": "下関市港湾局長（H6.4～8.6月）"},
    {"name": "北島 洋平", "agency": "資源エネルギー庁", "shimonoseki_title": "下関市副市長"},
    {"name": "工藤 健一", "agency": "防衛省", "shimonoseki_title": "港湾局長(H30.2.5～R1.6.30）"},
    {"name": "熊澤 至朗", "agency": "国交省", "shimonoseki_title": "都市整備部長（H25.4.1～H27.3.31）"},
    {"name": "九十九 悠太", "agency": "厚労省", "shimonoseki_title": "保健部長(H31.4.1～R3.7.6）"},
    {"name": "小栁 太郎", "agency": "地方公共団体金融機構", "shimonoseki_title": "財政部長（H15.4.1～H17.3.31）"},
    {"name": "酒井 貴司", "agency": "国交省（元）", "shimonoseki_title": "港湾局長（R4.4.1～R6.3.31）"},
    {"name": "佐々木 美紀", "agency": "国交省", "shimonoseki_title": "都市整備部長（H30.4.1～R2.3.31）"},
    {"name": "澤田 憲文", "agency": "国交省", "shimonoseki_title": "都市整備部長（H13.4.1～H15.3.31）"},
    {"name": "嶋倉 剛", "agency": "文科省（元）", "shimonoseki_title": "教育長（H20.5.26～H23.3.31）"},
    {"name": "杉田 博章", "agency": "内閣府", "shimonoseki_title": "港湾局長（R1.7.1～R4.3.31）"},
    {"name": "鈴木 章記", "agency": "厚労省（元）", "shimonoseki_title": "保健部長（H22.4.1～H26.７.１0）"},
    {"name": "鈴木 弘之", "agency": "民間", "shimonoseki_title": "港湾局長（H19.2.15～H21.6.24）"},
    {"name": "高橋 伸輔", "agency": "国交省", "shimonoseki_title": "都市整備部長（H15.4.1～H18.3.31）"},
    {"name": "田林 信哉", "agency": "総務省（元）", "shimonoseki_title": "財政部長（H22.8.9～H24.4.30）"},
    {"name": "谷川 勇二", "agency": "民間", "shimonoseki_title": "港湾局長（H14.4.1～H17.3.31）"},
    {"name": "東田 晃拓", "agency": "総務省", "shimonoseki_title": "財政部長（H19.7.9～H22.8.8）"},
    {"name": "中野 敏彦", "agency": "国交省（元）", "shimonoseki_title": "港湾局長（H17.4.1～H19.2.14）"},
    {"name": "中村 真弥", "agency": "水産庁", "shimonoseki_title": "農林水産振興部次長・水産課長事務取扱（H26.4.1～H28.3.31）"},
    {"name": "西村 尚己", "agency": "民間", "shimonoseki_title": "港湾局長（H24.7.1～H27.6.30）"},
    {"name": "野間 哲人", "agency": "総務省（島根県出向）", "shimonoseki_title": "財政部長（H26.4～H28.5）"},
    {"name": "野村 宗成", "agency": "総務省（国際機関出向）", "shimonoseki_title": "総合政策部長（H15.4.1～H18.6.30）"},
    {"name": "長谷川 学", "agency": "厚労省", "shimonoseki_title": "保健部長（H26.7.11～H28.6.30）"},
    {"name": "平澤 良輔", "agency": "国交省", "shimonoseki_title": "都市整備部長（R2.4.1～R4.3.31）"},
    {"name": "福本 怜", "agency": "厚労省", "shimonoseki_title": "保健部長(H28.7.1～H31.3.31）"},
    {"name": "舞立 昇治", "agency": "総務省（元）", "shimonoseki_title": "財政部長（H17.4.1～H19.7.8）"},
    {"name": "松林 直邦", "agency": "総務省", "shimonoseki_title": "財政部長（H28.6～H30.3）"},
    {"name": "宮本 卓次郎", "agency": "民間", "shimonoseki_title": "港湾局長（H10.4.1～H13.3.31）"},
    {"name": "山上 直人", "agency": "国交省", "shimonoseki_title": "都市整備部長"},
    {"name": "吉村 元吾", "agency": "国交省", "shimonoseki_title": "都市整備部長（H20.4.1～H22.3.31）"},
    {"name": "米澤 朋通", "agency": "総務省", "shimonoseki_title": "財政部長（H10.4.1～H12.3.31）"},
    {"name": "芳田 直樹", "agency": "復興庁", "shimonoseki_title": "副市長（H29.7.1～R3.6.30）"},
    {"name": "渡辺 真俊", "agency": "厚労省（元）", "shimonoseki_title": "保健部長（H19.8.1～H22.3.31）"},
    # 以下、元のWATCH_DATAにのみ存在したメンバー（役職不明のため空欄、必要に応じて追記してください）
    {"name": "坂本 修一", "agency": "文科省", "shimonoseki_title": "（データなし）"},
    {"name": "杉谷 郁哉", "agency": "中小企業庁", "shimonoseki_title": "（データなし）"},
    {"name": "入江 孝行", "agency": "消防庁", "shimonoseki_title": "（データなし）"},
    {"name": "田中 翔", "agency": "国交省", "shimonoseki_title": "（データなし）"},
    {"name": "時任 博之", "agency": "国交省", "shimonoseki_title": "（データなし）"}
]

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
        # SMTPサーバーのホスト名を修正 (://gmail.com -> smtp.gmail.com)
        smtpobj = smtplib.SMTP("smtp.gmail.com", 587)
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
                            # 通知メッセージに「下関時代の役職」を含めるようにフォーマット変更
                            hit_info = f"{member['name']}（現想定所属: {member['agency']} / 元下関市: {member['shimonoseki_title']}）"
                            hit_members.append(hit_info)
                    
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
