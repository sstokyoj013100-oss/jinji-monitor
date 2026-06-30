import os
import sys
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

# ログをリアルタイム強制出力
sys.stdout.reconfigure(line_buffering=True)

CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"

def normalize_text(text):
    """
    漢字の表記揺れ（高・髙など）と、すべての改行・空白を徹底的に排除・統一する
    """
    if not text:
        return ""
    # 空白、改行、タブをすべて削除
    text = re.sub(r'\s+', '', text)
    # 異体字（はしご高、立つ崎など）の文字ブレを通常漢字に強制統一
    text = text.replace('髙', '高')
    text = text.replace('﨑', '崎').replace('嵜', '崎')
    text = text.replace('栁', '柳').replace('柳', '柳')
    return text

def load_watch_data():
    combined_data = []
    print("[LOG] CSV名簿の読み込みを開始します...", flush=True)
    
    # ① 元幹部
    try:
        with open(CSV_EX_OFFICIALS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name,
                    "agency": row.get("agency", "").strip() or row.get("省庁", "不明"),
                    "memo": f"元下関市: {row.get('shimonoseki_title', '').strip()}",
                    "type": "【元幹部職員の異動検知】"
                })
    except Exception as e:
        print(f"[ERROR] {CSV_EX_OFFICIALS} 読込失敗: {e}", flush=True)

    # ② 重要ポジション
    try:
        with open(CSV_IMPORTANT_POSITIONS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("希望先氏名", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name,
                    "agency": row.get("省庁", "不明").strip(),
                    "memo": "重要ポジション",
                    "type": "【要監視重要ポジションの異動検知】"
                })
    except Exception as e:
        print(f"[ERROR] {CSV_IMPORTANT_POSITIONS} 読込失敗: {e}", flush=True)
        
    print(f"[LOG] 総監視人数: {len(combined_data)} 名", flush=True)
    return combined_data

WATCH_DATA = load_watch_data()

TO_ADDRESS = "sstokyoj@city.shimonoseki.yamaguchi.jp"
FROM_ADDRESS = "sstokyoj013100@gmail.com"
GMAIL_APP_PASSWORD = "qdfy qhwd bssx ptca"

TARGET_SITES = {
    "国土交通省(報道経由)": "https://www.mlit.go.jp/report/press/index.html",
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/kanbou/jidou/"
}

def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = FROM_ADDRESS
    msg["To"] = TO_ADDRESS
    msg["Date"] = formatdate(localtime=True)
    try:
        smtpobj = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        smtpobj.starttls()
        smtpobj.login(FROM_ADDRESS, GMAIL_APP_PASSWORD)
        smtpobj.sendmail(FROM_ADDRESS, [TO_ADDRESS], msg.as_string())
        smtpobj.close()
        print(f"[SUCCESS] メール送信に成功しました: {subject}", flush=True)
    except Exception as e:
        print(f"[CRITICAL ERROR] メール送信失敗: {e}", flush=True)

def check_ministries():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    
    for site_name, url in TARGET_SITES.items():
        print(f"[LOG] 巡回開始: {site_name}", flush=True)
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                if '.pdf' in href or 'jidou' in href:
                    if href.startswith('http'): target_url = href
                    else: target_url = "https://www.mlit.go.jp" + href if href.startswith('/') else url + href
                    if target_url not in links: links.append(target_url)
            
            print(f"[LOG] 発見したリンク数: {len(links)} 件", flush=True)

            for target_url in links:
                if not target_url.endswith('.pdf'): continue
                try:
                    pdf_res = requests.get(target_url, headers=headers, timeout=10)
                    with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
                        raw_text = "".join([page.extract_text() or "" for page in pdf.pages])
                    
                    # PDFテキストを正規化（改行を詰め、髙→高に変換）
                    normalized_pdf_text = normalize_text(raw_text)
                    
                    for member in WATCH_DATA:
                        # 名簿側の名前も正規化（空白を詰め、髙→高に変換）
                        c_name = normalize_text(member["name"])
                        if not c_name: continue
                        
                        # 1. 完全に一致するか
                        # 2. または、名前の全漢字がPDFに含まれており、かつ近接しているか（バラバラ死対策）
                        is_hit = False
                        if c_name in normalized_pdf_text:
                            is_hit = True
                        else:
                            chars = [c for c in c_name if c.strip()]
                            if len(chars) >= 2 and all(char in normalized_pdf_text for char in chars):
                                # 1文字目の周辺150文字以内に全文字があるかチェック
                                for m in re.finditer(re.escape(chars[0]), raw_text):
                                    surround = normalize_text(raw_text[max(0, m.start()-150):min(len(raw_text), m.end()+150)])
                                    if all(char in surround for char in chars):
                                        is_hit = True
                                        break
                        
                        if is_hit:
                            print(f"[HIT!!] 対象者を検知しました: {member['name']}", flush=True)
                            subject = f"{member['type']}{site_name} (該当: {member['name']})"
                            body = f"以下の人物に関する人事異動情報を検知しました。\n\n■ 該当者: {member['name']}\n■ サイト: {site_name}\n■ PDFリンク: {target_url}"
                            send_email(subject, body)
                            
                except Exception as pdf_e:
                    continue
            time.sleep(1)
        except Exception as e:
            print(f"[ERROR] {site_name} 巡回エラー: {e}", flush=True)

if __name__ == "__main__":
    check_ministries()
