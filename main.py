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

# 各省庁の「人事異動」が直接掲載される正確なURLに変更
TARGET_SITES = {
    "総務省": "https://www.soumu.go.jp/menu_news/s-news/jinji.html",
    "消防庁": "https://www.fdma.go.jp/pressrelease/jinji/",
    "国土交通省": "https://www.mlit.go.jp/about/kanbou/jidou/",
    "農林水産省": "https://www.maff.go.jp/j/press/jinji/",
    "水産庁": "https://www.jfa.maff.go.jp/j/press/jinji/",
    "厚生労働省": "https://www.mhlw.go.jp/kouseiroudoushou/shozaichi/jinji/",
    "内閣府": "https://www.cao.go.jp/jinji/jinji-shoukai.html",
    "こども家庭庁": "https://www.cfa.go.jp/pressrelease/",
    "文部科学省": "https://www.mext.go.jp/b_menu/shingi/jinji/index.htm",
    "復興庁": "https://www.reconstruction.go.jp/topics/main-cat2/sub-cat2-5/",
    "経済産業省": "https://www.meti.go.jp/annai/saiyou/jinji/index.html",
    "インターネット官報（本紙）": "https://kanpou.npb.go.jp/"
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
    """改行、スペース、タブなどのすべての空白文字を削除する"""
    if not text:
        return ""
    return re.sub(r'\s+', '', text)

def is_member_in_pdf(cleaned_name, raw_pdf_text, cleaned_pdf_text):
    """
    パースの崩れに対応した高度な氏名検知アルゴリズム
    1. 通常の1行一致チェック
    2. 文字がバラバラに崩れた場合の近接・順不同チェック
    """
    # パターン1: スペースを詰めて綺麗に一致する場合
    if cleaned_name in cleaned_pdf_text:
        return True
        
    # パターン2: pdfplumberのバグで「橋 伸 伸 輔 高」のように順序や文字が崩れた場合
    # 氏名を1文字ずつ分解（例: ['高', '橋', '伸', '輔']）
    chars = [c for c in cleaned_name if c.strip()]
    if len(chars) < 2:
        return False
        
    # 氏名のすべての漢字が、PDFの同一テキストブロック内に存在するか
    # 1ページ内に文字が散らばっているだけの場合の誤検知を防ぐため、
    # 最初の文字が見つかった位置の前後50文字以内に他の文字が密集しているかを判定
    if all(c in cleaned_pdf_text for c in chars):
        first_char = chars[0]
        # クリーニング前の生テキストから位置を特定して近接度をチェック
        for match in re.finditer(re.escape(first_char), raw_pdf_text):
            start_pos = max(0, match.start() - 100)
            end_pos = min(len(raw_pdf_text), match.end() + 100)
            surrounding_text = raw_pdf_text[start_pos:end_pos]
            # 周辺200文字以内に氏名の全漢字が含まれていれば高確率でヒットとみなす
            if all(c in surrounding_text for c in chars):
                return True
                
    return False

def check_ministries():
    # ユーザーエージェントを設定して、ロボット拒否対策を行う
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    for site_name, url in TARGET_SITES.items():
        print(f"【巡回中】{site_name} をチェックしています...")
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.encoding = response.apparent_encoding # 文字化け対策
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 各ページ内のリンク（aタグ）をすべて精査
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                
                # PDFリンク、または官報などのhtml形式の人事ページを対象にする
                if href.endswith('.pdf') or 'kanpou' in url:
                    # 相対パスを絶対URLに補正
                    if href.startswith('http'):
                        target_url = href
                    elif href.startswith('/'):
                        # ドメインのルートからの相対パス
                        from urllib.parse import urlparse
                        parsed_url = urlparse(url)
                        target_url = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
                    else:
                        # 現在のディレクトリからの相対パス
                        target_url = url.rstrip('/') + '/' + href.lstrip('/')
                    
                    # PDFまたは該当ページのコンテンツを取得
                    try:
                        res = requests.get(target_url, headers=headers, timeout=20)
                        if res.status_code != 200:
                            continue
                            
                        raw_text = ""
                        # PDFの場合のテキスト抽出
                        if target_url.endswith('.pdf'):
                            with pdfplumber.open(io.BytesIO(res.content)) as pdf:
                                # layout=Trueで表のセルや位置を崩さずに可能な限り維持して抽出
                                raw_text = "".join([page.extract_text(layout=True) or "" for page in pdf.pages])
                        else:
                            # 官報などHTMLの場合のテキスト抽出
                            html_soup = BeautifulSoup(res.text, 'html.parser')
                            raw_text = html_soup.get_text()
                        
                        cleaned_pdf_text = clean_text(raw_text)
                        
                        hit_members = []
                        mail_type = "【人事異動検知】"
                        
                        # 名簿と照合
                        for member in WATCH_DATA:
                            cleaned_name = clean_text(member["name"])
                            if not cleaned_name:
                                continue
                                
                            # 高度な検知ロジックを通す
                            if is_member_in_pdf(cleaned_name, raw_text, cleaned_pdf_text):
                                hit_info = f"{member['name']}（現想定所属: {member['agency']} / 備考: {member['memo']}）"
                                if hit_info not in hit_members:
                                    hit_members.append(hit_info)
                                    mail_type = member["type"]
                        
                        # 該当者がいた場合のみメールを送信
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
                            print(f"⇒ 【ヒット】{site_name} で対象者を検知、メールを送信しました。")
                            
                    except Exception as pdf_error:
                        # 1つのPDFエラーで全体が止まらないようにする
                        continue
            
            # サーバーに負荷をかけないよう、1省庁ごとに1秒待機
            time.sleep(1)
                        
        except Exception as e:
            print(f"【エラー】{site_name}のチェック中にエラーが発生しました: {e}")

if __name__ == "__main__":
    print("監視エージェントを起動します。")
    check_ministries()
    print("すべてのプロセスの巡回が終了しました。")
