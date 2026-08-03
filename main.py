
Gemini との会話
手動で走らせるときは、あくまでもテストなので、結果を履歴管理されるとテストが１回しかできなくなるし、変更時の違いもわからなくなるので、手動で走らせた場合は履歴管理しないようにしたい

手動実行（workflow_dispatch）時に履歴ファイル（detection_history.json）を更新しないようにするには、check_ministries() 関数の末尾にある 履歴更新・保存処理を is_manual_run の判定でスキップする 変更を加えます。  
TXT

該当箇所を以下のように修正してください。

修正コード
check_ministries() 関数の最後（# 履歴をマージして保存 付近）を次のように変更します。  
TXT

変更前
Python
    # 履歴をマージして保存
    updated_hits = list(history_hits_set.union(current_hits_keys))
    updated_warnings = list(history_warnings_set.union(current_warnings_urls))

    history_data["hits"] = updated_hits
    history_data["warnings"] = updated_warnings
    save_history(history_data)
変更後
Python
    # 履歴をマージして保存（手動実行時はテストのため履歴を保存・更新しない）
    if not is_manual_run:
        updated_hits = list(history_hits_set.union(current_hits_keys))
        updated_warnings = list(history_warnings_set.union(current_warnings_urls))

        history_data["hits"] = updated_hits
        history_data["warnings"] = updated_warnings
        save_history(history_data)
    else:
        print("【手動実行モード】テスト実行のため、検知履歴の更新・保存をスキップしました。")
追加の補足提案（任意）
上記に加え、6月〜8月の「重要ポジション監視開始・終了」のステータス管理フラグ（history_data["important_status"]）の更新も手動実行時に残したくない場合は、以下の2箇所の記述も if not is_manual_run: で囲むとより安全です。  
TXT

Python
    # 重要ポジション監視開始時
    if not is_manual_run:
        history_data["important_status"] = f"{now.year}_active"

    # 重要ポジション監視終了時
    if not is_manual_run:
        history_data["important_status"] = f"{now.year}_inactive"
これにより、手動実行時は detection_history.json に一切の変更が加わらなくなるため、何度テストを実行しても前日との差分比較や動作確認を繰り返し行うことができます。  
TXT

全文書き直してテキストファイルで提供してもらえるかね

Your TXT file is ready

TXT のアイコン
人事_手動履歴保存制御版
 TXT 
開く
手動実行（workflow_dispatch）時に検知履歴（detection_history.json）や状態フラグが更新・保存されないよう修正したPythonコードの全文をテキストファイル（人事_手動履歴保存制御版.txt）として生成いたしました。  
TXT

主な修正点
履歴保存の制御: check_ministries() 関数の末尾にある save_history(history_data) を if not is_manual_run: で囲み、手動実行時には履歴ファイルへの書き込みを行わないように変更しました。  
TXT

監視状態（ステータス）保存の制御: 6月〜8月の「重要ポジション監視開始・終了」の通知状態フラグ（history_data["important_status"]）についても、手動実行時は変更が保存されないように保護しました。  
TXT




Gemini は AI であり、間違えることがあります。

import csv
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formatdate
import io
import json
import os
import re
import smtplib
import time
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import pdfplumber
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# ================= 1. 監視対象名簿データの構築 =================
CSV_EX_OFFICIALS = "元幹部リスト.csv"
CSV_IMPORTANT_POSITIONS = "重要ポジション.csv"
HISTORY_FILE = "detection_history.json"


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", "", str(text))


def read_csv_flexible(file_path):
    rows = []
    if not os.path.exists(file_path):
        return rows

    with open(file_path, mode="r", encoding="utf-8-sig") as f:
        content = f.read()

    dialect = "excel"
    if "\t" in content and "," not in content:
        dialect = "excel-tab"

    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    for row in reader:
        cleaned_row = {k.strip(): v.strip() for k, v in row.items() if k and v}
        if cleaned_row:
            rows.append(cleaned_row)

    return rows


def load_watch_data():
    combined_data = []

    # 1. 元幹部リストの読み込み
    try:
        rows = read_csv_flexible(CSV_EX_OFFICIALS)
        for row in rows:
            name = row.get("name") or row.get("氏名") or row.get("名前", "")
            if not name:
                continue

            shimonoseki_title = (
                row.get("shimonoseki_title")
                or row.get("元下関役職")
                or row.get("役職", "データなし")
            )

            agency = (
                row.get("agency")
                or row.get("所属省庁")
                or row.get("省庁")
                or "元幹部職員"
            )

            combined_data.append({
                "name": name,
                "key_name": clean_text(name),
                "agency": agency,
                "memo": f"元下関役職: {shimonoseki_title}",
                "type": "【元幹部職員の異動検知】",
            })
    except Exception as e:
        print(f"CSVエラー1(元幹部リスト): {e}")

    # 2. 重要ポジションの読み込み
    current_month = datetime.now().month
    if current_month in [6, 7, 8]:
        try:
            rows = read_csv_flexible(CSV_IMPORTANT_POSITIONS)
            for row in rows:
                name = (
                    row.get("name")
                    or row.get("氏名")
                    or row.get("希望先氏名")
                    or row.get("名前", "")
                )
                if not name:
                    continue

                agency = (
                    row.get("agency")
                    or row.get("所属省庁")
                    or row.get("省庁")
                    or row.get("所属", "重要ポジション対象者")
                )

                combined_data.append({
                    "name": name,
                    "key_name": clean_text(name),
                    "agency": agency,
                    "memo": "重要ポジション対象者",
                    "type": "【要監視重要ポジションの異動検知】",
                })
        except Exception as e:
            print(f"CSVエラー2(重要ポジション): {e}")
    else:
        print(
            "【案内】現在時期外（9月〜5月）のため、重要ポジションの監視はスキップします。"
        )

    return combined_data


WATCH_DATA = load_watch_data()


# ================= 履歴管理用関数 =================
def load_history():
    default_data = {"hits": [], "warnings": [], "important_status": ""}
    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
        print("履歴ファイルが存在しないか空のため、新しく作成します。")
        save_history(default_data)
        return default_data
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("hits", [])
                data.setdefault("warnings", [])
                data.setdefault("important_status", "")
                return data
    except Exception as e:
        print(f"履歴ファイルの読み込みに失敗しました(初期化します): {e}")
    return default_data


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

GMAIL_APP_PASSWORD = os.environ.get(
    "GMAIL_APP_PASSWORD", "qdfy qhwd bssx ptca"
)

TARGET_SITES = {
    "総務省(人事・組織)": (
        "https://www.soumu.go.jp/menu_sosiki/annai/soshiki/jinji/index.html"
    ),
    "国土交通省(人事ページ)": "https://www.mlit.go.jp/about/R8jinji.html",
    "農林水産省(人事異動)": (
        "https://www.maff.go.jp/j/org/who/meibo/personnel_change/index.html"
    ),
    "厚生労働省(幹部名簿・人事)": (
        "https://www.mhlw.go.jp/kouseiroudoushou/kanbumeibo/index.html"
    ),
    "内閣府(幹部名簿)": "https://www.cao.go.jp/about/meibo.html",
    "こども家庭庁(人事)": "https://www.cfa.go.jp/about/jinji",
    "文部科学省(幹部名簿)": (
        "https://www.mext.go.jp/b_menu/soshiki2/kanbumeibo.htm"
    ),
    "復興庁(人事)": "https://www.reconstruction.go.jp/topics/cat-114/jinji/",
    "時事公報(人事ニュース)": "https://www.jihyo.co.jp/jinji_news/",
    "インターネット官報": "https://kanpou.npb.go.jp/",
}


# ================= 3. 通信・メール・解析の最適化関数 =================
def create_retry_session():
    session = requests.Session()
    retries = Retry(
        total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def send_emails_batch(email_tasks):
    if not email_tasks:
        return
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
    if not date_str:
        return None
    clean_str = date_str.replace("D:", "").replace("'", "").replace("Z", "")
    match = re.match(
        r"^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", clean_str
    )
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
    if not words:
        return ""
    words_sorted = sorted(words, key=lambda w: (-round(w["x0"] / 15), w["top"]))
    return "".join([w["text"] for w in words_sorted])


def get_surrounding_context_html_v2(name, html_lines):
    pattern = ".*".join([re.escape(c) for c in name if c.strip()])
    for line in html_lines:
        cleaned_line = re.sub(r"\s+", " ", line).strip()
        if not cleaned_line:
            continue
        match = re.search(pattern, clean_text(cleaned_line))
        if match or (clean_text(name) in clean_text(cleaned_line)):
            if len(cleaned_line) <= 150:
                return f"... {cleaned_line} ..."
            actual_match = re.search(
                ".*".join([re.escape(c) for c in name if c.strip()]), cleaned_line
            )
            if actual_match:
                start = max(0, actual_match.start() - 20)
                end = min(len(cleaned_line), actual_match.end() + 100)
                return f"... {cleaned_line[start:end].strip()} ..."
            return f"... {cleaned_line[:150].strip()} ..."
    return "周辺情報の取得失敗"


def get_surrounding_context_by_line(page, member_name):
    words = page.extract_words()
    if not words:
        return "周辺情報の取得失敗"
    cleaned_target = clean_text(member_name)
    full_text = "".join([w["text"] for w in words])
    if cleaned_target not in clean_text(full_text):
        return "ターゲットが見つかりません"
    first_char = member_name[0]
    target_words = [w for w in words if first_char in w["text"]]
    if not target_words:
        return "周辺情報の取得失敗(行特定不可)"
    base_word = target_words[0]
    base_top = base_word["top"]
    base_bottom = base_word["bottom"]
    tolerance = 5
    same_line_words = [
        w
        for w in words
        if (base_top - tolerance) <= w["top"] <= (base_bottom + tolerance)
    ]
    same_line_words_sorted = sorted(same_line_words, key=lambda w: w["x0"])
    line_text = " ".join([w["text"] for w in same_line_words_sorted])
    cleaned_line = re.sub(r"\s+", " ", line_text).strip()
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
    if len(chars) < 2:
        return False
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
    if not href_str or href_str.startswith(("javascript:", "mailto:", "#")):
        return None
    if "https:/" in href_str[6:] or "http:/" in href_str[5:]:
        matches = re.findall(r"https?://[^\s]+", href_str)
        if matches:
            target_url = matches[-1]
        else:
            return None
    else:
        target_url = urljoin(base_url, href_str)
    parsed_target = urlparse(target_url)
    host = parsed_target.netloc.lower()
    allowed_domains = [
        "soumu.go.jp",
        "mlit.go.jp",
        "maff.go.jp",
        "mhlw.go.jp",
        "cao.go.jp",
        "cfa.go.jp",
        "mext.go.jp",
        "reconstruction.go.jp",
        "meti.go.jp",
        "jihyo.co.jp",
        "kanpou.npb.go.jp",
    ]
    is_valid_domain = any(
        host == domain or host.endswith("." + domain)
        for domain in allowed_domains
    )
    if is_valid_domain and parsed_target.scheme in ["http", "https"]:
        return target_url
    return None


def collect_kanpou_links_dynamic(session, base_url, headers):
    kanpou_pdf_links = []
    try:
        res = session.get(base_url, headers=headers, timeout=20)
        res.encoding = res.apparent_encoding
        
        pdf_matches = re.findall(r'href=["']([^"']+\.pdf)["']', res.text, re.IGNORECASE)
        for pdf_path in pdf_matches:
            full_pdf_url = clean_and_validate_url(base_url, pdf_path)
            if full_pdf_url and full_pdf_url not in kanpou_pdf_links:
                kanpou_pdf_links.append(full_pdf_url)

        soup = BeautifulSoup(res.text, "html.parser")
        sub_pages = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if "kanpou" in href or href.endswith(".html") or href.endswith(".htm"):
                sub_url = clean_and_validate_url(base_url, href)
                if sub_url and sub_url not in sub_pages and sub_url != base_url:
                    sub_pages.append(sub_url)

        for sub_url in sub_pages[:10]:
            try:
                sub_res = session.get(sub_url, headers=headers, timeout=15)
                sub_pdf_matches = re.findall(r'href=["']([^"']+\.pdf)["']', sub_res.text, re.IGNORECASE)
                for pdf_path in sub_pdf_matches:
                    full_pdf_url = clean_and_validate_url(sub_url, pdf_path)
                    if full_pdf_url and full_pdf_url not in kanpou_pdf_links:
                        kanpou_pdf_links.append(full_pdf_url)
            except Exception:
                continue

    except Exception as e:
        print(f"官報リンク動的探索エラー: {e}")

    return kanpou_pdf_links


def collect_links_from_url(session, url, headers, deep_crawl=False):
    if "kanpou.npb.go.jp" in url:
        return collect_kanpou_links_dynamic(session, url, headers)

    if url.endswith(".pdf"):
        return [url]
    links = []
    try:
        res = session.get(url, headers=headers, timeout=20)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            target_url = clean_and_validate_url(url, href)
            if not target_url:
                continue
            # 【改善1】総務省等で異動の階層ページを広く取得できるようにキー判定を拡充
            if (
                href.endswith(".pdf")
                or href.endswith(".html")
                or href.endswith(".htm")
                or any(k in href for k in ["jidou", "jinji", "meibo", "renkei", "annai", "main_content"])
            ):
                if target_url not in links:
                    links.append(target_url)
        if deep_crawl:
            sub_links = []
            for l in links:
                if (l.endswith(".html") or l.endswith(".htm")) and (
                    any(k in l for k in ["jinji", "sosiki", "meibo", "saiyou", "b_menu", "intro", "annai"])
                ):
                    try:
                        time.sleep(0.5)
                        sub_res = session.get(l, headers=headers, timeout=20)
                        sub_soup = BeautifulSoup(sub_res.text, "html.parser")
                        for sub_a in sub_soup.find_all("a", href=True):
                            sub_href = sub_a["href"].strip()
                            sub_target = clean_and_validate_url(l, sub_href)
                            if (
                                sub_target
                                and (sub_target.endswith(".pdf") or "jinji" in sub_target)
                                and sub_target not in links
                                and sub_target not in sub_links
                            ):
                                sub_links.append(sub_target)
                    except Exception:
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
        with session.get(
            url, headers=current_headers, timeout=connect_timeout, stream=True
        ) as res:
            res.raise_for_status()
            content_type = res.headers.get("Content-Type", "")
            if is_meti_pdf and "pdf" not in content_type.lower():
                return None
            content = bytearray()
            start_time = time.time()
            for chunk in res.iter_content(chunk_size=524288):
                if time.time() - start_time > download_limit_time:
                    return None
                if chunk:
                    content.extend(chunk)
                size_limit = 52428800 if is_meti_pdf else 31457280
                if len(content) > size_limit:
                    return None
            return bytes(content)
    except:
        return None


def build_grouped_email_body_v2(hits_dict, history_keys, include_old=True):
    new_hits_body = ""
    old_hits_body = ""
    new_item_count = 0

    for key_name in sorted(hits_dict.keys()):
        info = hits_dict[key_name]
        new_sources, old_sources = [], []
        for src in info["sources"]:
            history_key = f"{key_name}_{src['url']}_{src['page']}"
            if history_key in history_keys:
                old_sources.append(src)
            else:
                new_sources.append(src)
        if new_sources:
            new_item_count += len(new_sources)
            new_hits_body += f"■ 氏名: {info['display_name']}\n"
            new_hits_body += f"  ・ 所属省庁: {info['agency']}\n"
            new_hits_body += f"  ・ 備考: {info['memo']}\n"
            new_hits_body += "  ・ 検知ソース:\n"
            for i, src in enumerate(new_sources, 1):
                new_hits_body += (
                    f"    [{i}] 発信元: {src['site_name']} ({src['page']})\n"
                )
                new_hits_body += f"        新所属(周辺テキスト): {src['new_position']}\n"
                new_hits_body += f"        掲載リンク: {src['url']}\n"
            new_hits_body += "\n"
        if old_sources and include_old:
            old_hits_body += (
                f"■ 氏名: {info['display_name']} (前回以前から継続掲載中)\n"
            )
            old_hits_body += f"  ・ 所属省庁: {info['agency']}\n"
            old_hits_body += f"  ・ 備考: {info['memo']}\n"
            old_hits_body += "  ・ 検知ソース:\n"
            for i, src in enumerate(old_sources, 1):
                old_hits_body += (
                    f"    [{i}] 発信元: {src['site_name']} ({src['page']})\n"
                )
                old_hits_body += f"        新所属(周辺テキスト): {src['new_position']}\n"
                old_hits_body += f"        掲載リンク: {src['url']}\n"
            old_hits_body += "\n"

    final_body = ""
    if new_hits_body:
        final_body += (
            "========================================\n【新着情報（前日からの差分項目）】\n========================================\n"
            + new_hits_body
        )
    if old_hits_body and include_old:
        final_body += (
            "========================================\n【過去の検知履歴（参考・継続掲載分）】\n========================================\n"
            + old_hits_body
        )
    return final_body, new_item_count


# ================= 4. メイン監視処理 =================
def check_ministries():
    is_manual_run = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if is_manual_run:
        print("【手動実行モード】テスト実行のため「定期報告メール」のみを送信します。履歴の更新・保存はスキップされます。")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
            " like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
    }
    now = datetime.now()
    thirty_days_ago = now - timedelta(days=30)
    session = create_retry_session()

    history_data = load_history()
    history_hits_set = set(history_data.get("hits", []))
    history_warnings_set = set(history_data.get("warnings", []))
    last_important_status = history_data.get("important_status", "")

    overall_results = {}
    ex_officials_hits = {}
    important_positions_hits = {}
    image_pdf_warnings = []
    email_tasks = []
    current_hits_keys = []
    current_warnings_urls = []
    execution_error_occurred = False
    error_message = ""

    current_month = now.month

    if current_month in [6, 7, 8] and last_important_status != f"{now.year}_active":
        notice_subject = "【通知】重要ポジション監視の開始（6月下旬〜8月末期間）"
        notice_body = (
            "人事異動監視システムよりお知らせです。\n\n"
            f"本日（{now.strftime('%Y年%m月%d日')}）より、重要ポジション対象者の巡回監視を開始いたしました。\n"
            "※8月末日まで（9月1日停止）監視を実行します。"
        )
        if not is_manual_run:
            email_tasks.append((notice_subject, notice_body, TO_ADDRESS_DETECT))
            email_tasks.append((notice_subject, notice_body, TO_ADDRESS_REPORT))
            history_data["important_status"] = f"{now.year}_active"

    elif current_month not in [6, 7, 8] and last_important_status.endswith("_active"):
        notice_subject = "【通知】重要ポジション監視の終了"
        notice_body = (
            "人事異動監視システムよりお知らせです。\n\n"
            f"8月末日を経過したため、本日（{now.strftime('%Y年%m月%d日')}）をもって重要ポジション対象者の監視を自動停止いたしました。\n"
            "※元幹部職員の監視は継続して通年実行されます。"
        )
        if not is_manual_run:
            email_tasks.append((notice_subject, notice_body, TO_ADDRESS_DETECT))
            email_tasks.append((notice_subject, notice_body, TO_ADDRESS_REPORT))
            history_data["important_status"] = f"{now.year}_inactive"

    try:
        for site_name, url in TARGET_SITES.items():
            print(f"【巡回中】{site_name} をチェックしています...")
            overall_results[site_name] = {"status": "チェック未完了(エラーの可能性)"}
            deep_crawl_flag = True if "総務省" in site_name or "文部科学省" in site_name else False
            current_headers = headers.copy()
            if "meti.go.jp" in url:
                current_headers["Referer"] = "https://www.meti.go.jp/"
            
            links = collect_links_from_url(
                session, url, current_headers, deep_crawl=deep_crawl_flag
            )
            if url not in links and "kanpou.npb.go.jp" not in url:
                links.insert(0, url)
                
            checked_count, hits_in_site = 0, 0

            for target_url in links:
                if not (
                    target_url.endswith(".pdf")
                    or target_url.endswith(".html")
                    or target_url.endswith(".htm")
                    or "kanpou.npb.go.jp" in target_url
                    or "jihyo.co.jp" in target_url
                ):
                    continue
                try:
                    file_content = download_file_safely(session, target_url, headers)
                    if not file_content:
                        continue
                    pages_data, is_image_pdf, html_lines_extracted = [], False, []

                    if target_url.endswith(".pdf"):
                        checked_count += 1
                        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                            meta = pdf.metadata or {}
                            pdf_date_str = meta.get("ModDate") or meta.get("CreationDate")
                            pdf_date = parse_pdf_date(pdf_date_str)
                            
                            # 【改善2】時系列前後・メタデータ不順に対応するため総務省等の異動ページからのPDFは日付フィルタを除外
                            is_static_or_key_site = (
                                "meibo" in target_url
                                or "list_ja.pdf" in target_url
                                or "幹部名簿" in site_name
                                or "総務省" in site_name
                            )
                            if pdf_date and not is_static_or_key_site and "kanpou" not in target_url:
                                if pdf_date < thirty_days_ago:
                                    continue

                            for idx, page in enumerate(pdf.pages, 1):
                                # 【改善3】レイアウト付き抽出と通常抽出の両方をフォールバック取得
                                page_raw = page.extract_text(layout=True) or ""
                                page_raw_simple = page.extract_text(layout=False) or ""
                                
                                if (
                                    "農林水産省" in site_name
                                    or "総務省" in site_name
                                    or "インターネット官報" in site_name
                                    or "経済産業省" in site_name
                                    or (len(page_raw.strip()) < 5 and len(pdf.pages) > 0)
                                ):
                                    v_text = extract_vertical_text_from_page(page)
                                    if v_text.strip():
                                        page_raw += "\n" + v_text
                                
                                full_page_text = page_raw + "\n" + page_raw_simple
                                pages_data.append(
                                    (str(idx), full_page_text, clean_text(full_page_text), page)
                                )
                        total_raw_len = sum(len(p[1].strip()) for p in pages_data)
                        if len(file_content) > 50000 and total_raw_len < 10:
                            is_image_pdf = True
                    else:
                        checked_count += 1
                        html_soup = BeautifulSoup(
                            file_content.decode("utf-8", errors="ignore"), "html.parser"
                        )
                        for s in html_soup(["script", "style", "nav", "footer"]):
                            s.decompose()
                        html_text = html_soup.get_text()
                        html_lines_extracted = [
                            line.strip() for line in html_soup.strings if line.strip()
                        ]
                        pages_data.append(("-", html_text, clean_text(html_text), None))

                    if not is_image_pdf:
                        for member in WATCH_DATA:
                            cleaned_name = member["key_name"]
                            if not cleaned_name:
                                continue
                            for page_num, raw_text, cleaned_text_data, page_obj in pages_data:
                                if is_member_in_text(
                                    cleaned_name, raw_text, cleaned_text_data
                                ):
                                    new_position_hint = (
                                        get_surrounding_context_by_line(page_obj, member["name"])
                                        if page_obj
                                        else get_surrounding_context_html_v2(
                                            member["name"], html_lines_extracted
                                        )
                                    )
                                    page_label = (
                                        f"該当ページ: {page_num} ページ"
                                        if page_num != "-"
                                        else "WEBページ(HTML上に直接記載)"
                                    )
                                    source_detail = {
                                        "site_name": site_name,
                                        "url": target_url,
                                        "page": page_label,
                                        "new_position": new_position_hint,
                                    }
                                    target_dict = (
                                        ex_officials_hits
                                        if member["type"] == "【元幹部職員の異動検知】"
                                        else important_positions_hits
                                    )
                                    if cleaned_name not in target_dict:
                                        target_dict[cleaned_name] = {
                                            "display_name": member["name"],
                                            "agency": member["agency"],
                                            "memo": member["memo"],
                                            "sources": [],
                                        }
                                    if not any(
                                        s["url"] == target_url and s["page"] == source_detail["page"]
                                        for s in target_dict[cleaned_name]["sources"]
                                    ):
                                        target_dict[cleaned_name]["sources"].append(source_detail)
                                        hits_in_site += 1
                                        current_hits_keys.append(
                                            f"{cleaned_name}_{target_url}_{page_label}"
                                        )
                    if is_image_pdf and (
                        "jidou" in target_url
                        or "jinji" in target_url
                        or "meibo" in target_url
                        or "kanpou" in target_url
                    ):
                        warn_info = {"site_name": site_name, "url": target_url}
                        if warn_info not in image_pdf_warnings:
                            image_pdf_warnings.append(warn_info)
                        current_warnings_urls.append(target_url)
                except:
                    continue
            overall_results[site_name]["status"] = "正常巡回完了"
            overall_results[site_name][
                "summary"
            ] = f"検証対象数: {checked_count}件 / ヒット数: {hits_in_site}件"
            time.sleep(1.0)
    except Exception as main_err:
        execution_error_occurred = True
        error_message = str(main_err)

    # ================= メールタスク作成と履歴の更新 =================
    ex_official_new_count = 0
    important_new_count = 0
    warnings_new_count = 0
    diff_report_summary = ""
    detailed_report_content = ""

    # 元幹部
    if ex_officials_hits:
        detect_body_content, new_count = build_grouped_email_body_v2(
            ex_officials_hits, history_hits_set, include_old=True
        )
        ex_official_new_count = new_count
        if ex_official_new_count > 0 and not is_manual_run:
            email_tasks.append((
                "【元幹部職員の異動検知】人事異動新規掲載報告",
                "以下の元幹部職員に関する人事異動情報を検知しました。\n\n"
                + detect_body_content
                + "※このメールは自動監視エージェントから送信されています。",
                TO_ADDRESS_DETECT,
            ))

        report_body_content, _ = build_grouped_email_body_v2(
            ex_officials_hits, history_hits_set, include_old=False
        )
        if report_body_content:
            detailed_report_content += (
                "【元幹部職員の新着検知内容】\n" + report_body_content + "\n"
            )

    if ex_official_new_count > 0:
        diff_report_summary += (
            f"・【元幹部職員の異動検知】: 新規掲載が {ex_official_new_count} 件ありました。\n"
        )
    else:
        diff_report_summary += "・【元幹部職員の異動検知】: 新規掲載はありませんでした。\n"

    # 重要ポジション
    if important_positions_hits:
        detect_body_content, new_count = build_grouped_email_body_v2(
            important_positions_hits, history_hits_set, include_old=True
        )
        important_new_count = new_count
        if important_new_count > 0 and not is_manual_run:
            email_tasks.append((
                "【要監視重要ポジションの異動検知】人事異動新規掲載報告",
                "以下の重要ポジションに関する人事異動情報を検知しました。\n\n"
                + detect_body_content
                + "※このメールは自動監視エージェントから送信されています。",
                TO_ADDRESS_DETECT,
            ))

        report_body_content, _ = build_grouped_email_body_v2(
            important_positions_hits, history_hits_set, include_old=False
        )
        if report_body_content:
            detailed_report_content += (
                "【要監視重要ポジションの新着検知内容】\n"
                + report_body_content
                + "\n"
            )

    if important_new_count > 0:
        diff_report_summary += f"・【要監視重要ポジションの異動検知】: 新規掲載が {important_new_count} 件ありました。\n"
    else:
        diff_report_summary += "・【要監視重要ポジションの異動検知】: 新規掲載はありませんでした。\n"

    # 画像PDF警告
    new_warnings = [
        w for w in image_pdf_warnings if w["url"] not in history_warnings_set
    ]
    warnings_new_count = len(new_warnings)
    if warnings_new_count > 0:
        body = (
            "※警告: 文字情報が抽出できない「画像化されたPDF」が新しく検出されました。\n手動でご確認ください。\n\n"
        )
        for w in new_warnings:
            body += f"■ 発信元: {w['site_name']}\n■ リンク: {w['url']}\n"

        if not is_manual_run:
            email_tasks.append((
                "【要手動確認・画像PDF検出一括報告】",
                body + "----------------------------------------\n",
                TO_ADDRESS_DETECT,
            ))
        diff_report_summary += f"・【要手動確認・画像PDF検出一括報告】: 新規検出が {warnings_new_count} 件ありました。\n"
        detailed_report_content += "【新着・画像PDF検出】\n" + body + "\n"
    else:
        diff_report_summary += "・【要手動確認・画像PDF検出一括報告】: 新規検出はありませんでした。\n"

    # 定期報告メールの作成
    if is_manual_run or execution_error_occurred or (ex_official_new_count > 0 or important_new_count > 0 or warnings_new_count > 0):
        if execution_error_occurred:
            report_subject = "【⚠️システム異常検知】人事異動監視巡回エラー"
            report_body = (
                "プログラム実行エラーが発生しました。\n"
                f"エラー内容: {error_message}\n\n"
            )
        else:
            manual_prefix = "【手動テスト実行】" if is_manual_run else ""
            report_subject = f"{manual_prefix}【定期報告】人事異動監視エージェント・巡回完了通知"
            report_body = (
                f"人事異動の監視プログラムが実行されました。（モード: {'手動テスト実行' if is_manual_run else '自動スケジュール実行'}）\n\n"
            )

        report_body += "========================================\n"
        report_body += "【前日からの新規差分・掲載状況】\n"
        report_body += "========================================\n"
        report_body += diff_report_summary + "\n"

        if detailed_report_content:
            report_body += "========================================\n"
            report_body += "【新着検知データ詳細】\n"
            report_body += "========================================\n"
            report_body += detailed_report_content + "\n"

        report_body += "========================================\n"
        report_body += "【各省庁サイトの巡回結果一覧】\n"
        report_body += "========================================\n"
        for site, res in overall_results.items():
            report_body += (
                f"■ {site}\n"
                f"  ステータス: {res['status']}\n"
                f"  {res.get('summary', '')}\n"
                "----------------------------------------\n"
            )
        report_body += (
            f"\n監視対象データ数: 計 {len(WATCH_DATA)} 名\n※自動送信メール"
        )

        email_tasks.append((report_subject, report_body, TO_ADDRESS_REPORT))

    # まとめてメール送信
    if email_tasks:
        send_emails_batch(email_tasks)

    # 履歴をマージして保存（手動実行時はテストのため履歴を保存・更新しない）
    if not is_manual_run:
        updated_hits = list(history_hits_set.union(current_hits_keys))
        updated_warnings = list(history_warnings_set.union(current_warnings_urls))

        history_data["hits"] = updated_hits
        history_data["warnings"] = updated_warnings
        save_history(history_data)
    else:
        print("【手動実行モード】テスト実行のため、検知履歴の更新・保存をスキップしました。")


if __name__ == "__main__":
    check_ministries()
人事_手動履歴保存制御版.txt
「人事_手動履歴保存制御版.txt」を表示しています。
