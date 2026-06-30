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

# GitHub Actionsの画面へ文字をその瞬間に強制出力させる（ログ消失の防止）
sys.stdout.reconfigure(line_buffering=True)

CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"

def load_watch_data():
    combined_data = []
    print("[LOG] CSV名簿の読み込みを開始します...", flush=True)
    # 元幹部
    try:
        with open(CSV_EX_OFFICIALS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name, "agency": row.get("agency", "").strip() or row.get("省庁", "不明"),
                    "memo": f"元下関市: {row.get('shimonoseki_title', '').strip()}", "type": "【元幹部職員の異動検知】"
                })
        print(f"[LOG] {CSV_EX_OFFICIALS} から読込完了", flush=True)
    except Exception as e:
        print(f"[ERROR] {CSV_EX_OFFICIALS} の読込失敗: {e}", flush=True)

    # 重要ポジション
    try:
        with open(CSV_IMPORTANT_POSITIONS, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("希望先氏名", "").strip() or row.get("氏名", "").strip()
                if not name: continue
                combined_data.append({
                    "name": name, "agency": row.get("省庁", "不明").strip(),
                    "memo": "重要ポジション", "type": "【要監視重要ポジションの異動検知】"
                })
        print(f"[LOG] {CSV_IMPORTANT_POSITIONS} から読込完了", flush=True)
    except Exception as e:
        print(f"[ERROR] {CSV_IMPORTANT_POSITIONS} の読込失敗: {e}", flush=True)
        
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
        print(f"[LOG] Gmailサーバー(smtp.gmail.com)に接続を試みます...", flush=True)
        smtpobj = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        smtpobj.starttls()
        smtpobj.login(FROM_ADDRESS, GMAIL_APP_PASSWORD)
        smtpobj.sendmail(FROM_ADDRESS, [TO_ADDRESS], msg.as_string())
        smtpobj.close()
        print(f"[SUCCESS] メール送信に成功しました: {subject}", flush=True)
    except Exception as e:
        print(f"[CRITICAL ERROR] メール送信に失敗しました。GitHubからの海外アクセスがGoogleにブロックされた可能性があります。 エラー詳細: {e}", flush=True)

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', '', text)

def check_ministries():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}
    
    for site_name, url in TARGET_SITES.items():
        print(f"[LOG] 巡回開始: {site_name} ({url})", flush=True)
        try:
            res = requests.get(url, headers=headers, timeout=10)
            print(f"[LOG] 接続ステータス: {res.status_code}", flush=True)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                if '.pdf' in href or 'jidou' in href:
                    if href.startswith('http'): target_url = href
                    else: target_url = "https://www.mlit.go.jp" + href if href.startswith('/') else url + href
                    if target_url not in links: links.append(target_url)
            
            print(f"[LOG] 解析候補のPDFリンクを {len(links)} 件発見しました。", flush=True)

            for target_url in links:
                if not target_url.endswith('.pdf'): continue
                print(f"[LOG] PDFダウンロード中: {target_url}", flush=True)
                try:
                    pdf_res = requests.get(target_url, headers=headers, timeout=10)
                    with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
                        raw_text = "".join([page.extract_text() or "" for page in pdf.pages])
                    
                    cleaned_text = clean_text(raw_text)
                    print(f"[LOG] PDFから {len(cleaned_text)} 文字のテキストを抽出しました。", flush=True)
                    
                    # 名前の判定（高橋さん等）
                    for member in WATCH_DATA:
                        c_name = clean_text(member["name"])
                        # バラバラ死対策として全文字が含まれるか簡易判定
                        if c_name in cleaned_text or all(char in cleaned_text for char in c_name if char.strip()):
                            print(f"[HIT!!] ヒットしました: {member['name']}", flush=True)
                            subject = f"{member['type']}{site_name}"
                            body = f"検知対象: {member['name']}\nリンク: {target_url}"
                            send_email(subject, body)
                except Exception as pdf_e:
                    print(f"[WARNING] PDF解析スキップ ({target_url}): {pdf_e}", flush=True)
        except Exception as e:
            print(f"[ERROR] {site_name} の巡回中にエラー: {e}", flush=True)

if __name__ == "__main__":
    check_ministries()
    print("[LOG] すべての処理が終了しました。", flush=True)
