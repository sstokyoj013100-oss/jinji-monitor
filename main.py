import requests
from bs4 import BeautifulSoup
import io
import sys

# 画面への出力をその瞬間に強制する設定（ログが出ない問題を解決）
sys.stdout.reconfigure(line_buffering=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"
}

def test_run():
    print("【診断開始】プログラムは正常に起動しました。", flush=True)
    
    # 1. 人事発表ページ
    url_jinji = "https://www.mlit.go.jp/about/kanbou/jidou/"
    print(f"【アクセス中】国交省・人事ページへ接続します... URL: {url_jinji}", flush=True)
    
    try:
        # timeoutを「3秒」と極限まで短くし、フリーズを強制回避
        res = requests.get(url_jinji, headers=headers, timeout=3)
        print(f"【接続成功】ステータスコード: {res.status_code}", flush=True)
        
        soup = BeautifulSoup(res.text, 'html.parser')
        links = [a['href'] for a in soup.find_all('a', href=True)]
        print(f"【結果】ページ内から {len(links)} 件のリンクを発見しました。", flush=True)
        
        pdf_links = [l for l in links if '.pdf' in l]
        print(f"【結果】そのうち、PDFリンクは {len(pdf_links)} 件です。", flush=True)
        
    except requests.exceptions.Timeout:
        print("❌【原因判明】国交省のサーバー側で通信がタイムアウト（拒否・無視）されました。相手の防御壁に引っかかっています。", flush=True)
    except Exception as e:
        print(f"❌【エラー】接続中に次の問題が発生しました: {e}", flush=True)

if __name__ == "__main__":
    test_run()
    print("【診断終了】", flush=True)
