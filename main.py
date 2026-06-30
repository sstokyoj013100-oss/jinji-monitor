import requests
from bs4 import BeautifulSoup
import io
import pdfplumber

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def diagnose():
    print("=== 国交省 接続診断スタート ===")
    
    # 1. 人事ページへのアクセス確認
    url_jinji = "https://www.mlit.go.jp/about/kanbou/jidou/"
    try:
        res = requests.get(url_jinji, headers=headers, timeout=15)
        print(f"① 人事ページ ステータスコード: {res.status_code} (200ならOK)")
        
        soup = BeautifulSoup(res.text, 'html.parser')
        links = [a['href'] for a in soup.find_all('a', href=True)]
        pdf_links = [l for l in links if '.pdf' in l]
        print(f"   ページ内の全リンク数: {len(links)} 件")
        print(f"   そのうちPDFのリンク数: {len(pdf_links)} 件")
        if pdf_links:
            print(f"   見つかったPDFの例: {pdf_links[:2]}")
            
            # 2. 最初に見つかったPDFの読込テスト
            test_pdf = pdf_links[0]
            if not test_pdf.startswith('http'):
                test_pdf = "https://www.mlit.go.jp" + test_pdf if test_pdf.startswith('/') else url_jinji + test_pdf
            
            print(f"② テストPDFへの接続検証: {test_pdf}")
            pdf_res = requests.get(test_pdf, headers=headers, timeout=15)
            print(f"   PDFダウンロードステータス: {pdf_res.status_code}")
            
            with pdfplumber.open(io.BytesIO(pdf_res.content)) as pdf:
                text = "".join([p.extract_text() or "" for p in pdf.pages])
                print(f"   PDFから抽出できた文字数: {len(text)} 文字")
                if len(text) > 0:
                    print(f"   PDFの冒頭テキスト: {text[:50]}...")
                else:
                    print("   [警告] PDFから文字が1文字も抽出できません（画像PDFの可能性大）")
                    
    except Exception as e:
        print(f"【エラー発生】診断中に問題が発生しました: {e}")

if __name__ == "__main__":
    diagnose()
