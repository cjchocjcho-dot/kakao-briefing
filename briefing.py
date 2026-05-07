from dotenv import load_dotenv
import os
load_dotenv()

import yfinance as yf
import requests
import json
import re
from datetime import datetime, timedelta
import anthropic
import pytz
from PIL import Image, ImageDraw, ImageFont
import base64

# 한국 시간 기준
KST = pytz.timezone('Asia/Seoul')
now = datetime.now(KST)

# ===== 설정 =====
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN")
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

SECTORS = ["반도체", "AI", "정유", "선박", "해운", "물류", "원자재"]

def refresh_kakao_token():
    url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
        "client_secret": KAKAO_CLIENT_SECRET,
    }
    r = requests.post(url, data=data)
    result = r.json()
    if "access_token" in result:
        new_token = result["access_token"]
        print("카카오 토큰 갱신 성공!")
        update_github_secret("KAKAO_ACCESS_TOKEN", new_token)
        if "refresh_token" in result:
            update_github_secret("KAKAO_REFRESH_TOKEN", result["refresh_token"])
        return new_token
    else:
        print(f"토큰 갱신 실패: {result}")
        return KAKAO_ACCESS_TOKEN

def update_github_secret(secret_name, secret_value):
    try:
        repo = GITHUB_REPO
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        key_url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
        key_resp = requests.get(key_url, headers=headers).json()
        public_key = key_resp["key"]
        key_id = key_resp["key_id"]

        from base64 import b64encode
        from nacl import encoding, public
        public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(public_key_obj)
        encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
        encrypted_value = b64encode(encrypted).decode("utf-8")

        secret_url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
        payload = {"encrypted_value": encrypted_value, "key_id": key_id}
        requests.put(secret_url, headers=headers, json=payload)
        print(f"{secret_name} 업데이트 완료!")
    except Exception as e:
        print(f"Secret 업데이트 실패: {e}")

def get_naver_index(code):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://m.stock.naver.com/api/index/{code}/price?pageSize=5&pageNo=1"
        r = requests.get(url, headers=headers)
        data = r.json()
        today_str = now.strftime("%Y-%m-%d")
        filtered = [d for d in data if d["localTradedAt"] != today_str]
        curr = float(str(filtered[0]["closePrice"]).replace(",", ""))
        prev = float(str(filtered[1]["closePrice"]).replace(",", ""))
        change = (curr - prev) / prev * 100
        arrow = "▲" if change >= 0 else "▼"
        return f"{curr:,.2f} {arrow}{abs(change):.2f}%"
    except Exception as e:
        print(f"네이버 지수 오류 ({code}): {e}")
        return "오류"

def get_naver_stock(ticker):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://m.stock.naver.com/api/stock/{ticker}/price?pageSize=5&pageNo=1"
        r = requests.get(url, headers=headers)
        data = r.json()
        today_str = now.strftime("%Y-%m-%d")
        filtered = [d for d in data if d["localTradedAt"] != today_str]
        curr = float(str(filtered[0]["closePrice"]).replace(",", ""))
        prev = float(str(filtered[1]["closePrice"]).replace(",", ""))
        change = (curr - prev) / prev * 100
        arrow = "▲" if change >= 0 else "▼"
        return f"{curr:,.0f} {arrow}{abs(change):.2f}%"
    except Exception as e:
        print(f"네이버 종목 오류 ({ticker}): {e}")
        return "오류"

def get_market_data():
    result = {}
    result["코스피"] = get_naver_index("KOSPI")
    result["코스닥"] = get_naver_index("KOSDAQ")

    kr_tickers = {
        "삼성전자": "005930",
        "SK하이닉스": "000660",
        "네이버": "035420",
    }
    for name, ticker in kr_tickers.items():
        result[name] = get_naver_stock(ticker)

    us_tickers = {
        "라인야후": "4689.T",
        "애플": "AAPL",
        "테슬라": "TSLA",
        "구글": "GOOGL",
        "나스닥": "^IXIC",
        "S&P500": "^GSPC",
        "원/달러": "KRW=X",
        "WTI유가": "CL=F",
    }
    end = now.strftime("%Y-%m-%d")
    start = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    for name, ticker in us_tickers.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=start, end=end)
            hist = hist.dropna()
            if len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                curr = float(hist["Close"].iloc[-1])
                change = (curr - prev) / prev * 100
                arrow = "▲" if change > 0 else "▼"
                result[name] = f"{curr:,.1f} {arrow}{abs(change):.1f}%"
            else:
                result[name] = "데이터없음"
        except:
            result[name] = "오류"

    return result

def get_news():
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    sector_query = " OR ".join(SECTORS)
    query = f"미국증시 OR 월가 OR 나스닥 OR {sector_query}"
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q={query}"
        f"&language=ko"
        f"&from={yesterday}"
        f"&to={today}"
        f"&pageSize=10"
        f"&sortBy=publishedAt"
        f"&apiKey={NEWSAPI_KEY}"
    )
    try:
        r = requests.get(url)
        articles = r.json().get("articles", [])
        return [a["title"] for a in articles[:8]]
    except:
        return ["뉴스를 가져오지 못했습니다."]

def get_ai_analysis(market_data, news_headlines):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today_str = now.strftime("%Y년 %m월 %d일")
    data_str = json.dumps(market_data, ensure_ascii=False)
    news_str = "\n".join([f"- {n}" for n in news_headlines])
    sectors_str = ", ".join(SECTORS)

    prompt = f"""당신은 경력 15년의 국내 증권사 수석 애널리스트입니다.
오늘 날짜는 {today_str}이며, 지금은 아침 장 시작 전입니다.
아래는 전날 마감된 시장 데이터와 간밤에 나온 주요 뉴스입니다.
이를 바탕으로 오늘 코스피 시장을 전망하는 브리핑을 작성해주세요.

[전일 마감 시장 데이터]
{data_str}

[간밤 주요 뉴스]
{news_str}

[관심 섹터]
{sectors_str}

반드시 아래 형식으로만 작성해주세요. 제목이나 날짜는 따로 쓰지 마세요. 각 섹션당 3줄 이내로 간결하게 작성해주세요:

🌙 간밤 미국 증시 마감 요약
(나스닥/S&P500 흐름과 주요 이슈를 2~3줄로 설명)

📰 섹터별 주요 뉴스
(관심 섹터 중 중요한 것 위주로 헤드라인 + 한줄 의미)

🔮 오늘 코스피 전망
- 예상 등락 방향과 근거
- 주목할 종목 또는 섹터
- 리스크 요인
- 예상 코스피 지수 범위

💬 한줄 총평"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def make_briefing_image(market_data, analysis):
    WIDTH, HEIGHT = 800, 1050
    BG = "#0D1117"
    CARD = "#161B22"
    BORDER = "#21262D"
    ACCENT = "#58A6FF"
    GREEN = "#3FB950"
    RED = "#F85149"
    YELLOW = "#D29922"
    WHITE = "#E6EDF3"
    GRAY = "#8B949E"

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # 한글 폰트
    font_paths = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    def load_font(size, bold=False):
        for path in font_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except:
                    continue
        return ImageFont.load_default()

    f_title = load_font(26, bold=True)
    f_section = load_font(18, bold=True)
    f_body = load_font(16)
    f_small = load_font(13)

    def rr(xy, r, fill, outline=None):
        x1, y1, x2, y2 = xy
        draw.rounded_rectangle([x1, y1, x2, y2], radius=r, fill=fill, outline=outline, width=1)

    def section(y, title, rows, tc=ACCENT):
        h = 48 + len(rows) * 36
        rr((30, y, WIDTH-30, y+h), 10, CARD, BORDER)
        draw.text((52, y+13), title, font=f_section, fill=tc)
        draw.line([(50, y+44), (WIDTH-50, y+44)], fill=BORDER, width=1)
        for i, (label, value, color) in enumerate(rows):
            ry = y + 52 + i*34
            draw.text((55, ry), label, font=f_body, fill=GRAY)
            draw.text((WIDTH-55, ry), value, font=f_body, fill=color, anchor="ra")
        return y + h + 12

    # 헤더
    rr((30, 20, WIDTH-30, 95), 10, CARD, ACCENT)
    draw.text((52, 33), "📊 오늘의 시장 브리핑", font=f_title, fill=WHITE)
    draw.text((52, 68), now.strftime("%Y.%m.%d (%a)  |  매일 오전 7시 자동 발송"), font=f_small, fill=GRAY)

    y = 115

    def color(v):
        return GREEN if "▲" in v else RED

    y = section(y, "🇺🇸 미국 증시", [
        ("나스닥", market_data["나스닥"], color(market_data["나스닥"])),
        ("S&P500", market_data["S&P500"], color(market_data["S&P500"])),
    ])
    y = section(y, "📈 국내 증시 (전일 종가)", [
        ("코스피", market_data["코스피"], color(market_data["코스피"])),
        ("코스닥", market_data["코스닥"], color(market_data["코스닥"])),
    ])
    y = section(y, "💼 주요 종목 (전일 종가)", [
        ("삼성전자", market_data["삼성전자"], color(market_data["삼성전자"])),
        ("SK하이닉스", market_data["SK하이닉스"], color(market_data["SK하이닉스"])),
        ("네이버", market_data["네이버"], color(market_data["네이버"])),
        ("애플", market_data["애플"], color(market_data["애플"])),
        ("테슬라", market_data["테슬라"], color(market_data["테슬라"])),
        ("구글", market_data["구글"], color(market_data["구글"])),
    ])
    y = section(y, "💱 환율 / 유가", [
        ("원/달러", market_data["원/달러"], color(market_data["원/달러"])),
        ("WTI유가", market_data["WTI유가"], color(market_data["WTI유가"])),
    ])

    # AI 분석 요약 (첫 두 줄만)
    lines = [l for l in analysis.split('\n') if l.strip()][:4]
    ah = 50 + len(lines) * 26
    rr((30, y, WIDTH-30, y+ah), 10, CARD, YELLOW)
    draw.text((52, y+13), "🔮 AI 코스피 전망", font=f_section, fill=YELLOW)
    draw.line([(50, y+44), (WIDTH-50, y+44)], fill=BORDER, width=1)
    for i, line in enumerate(lines):
        draw.text((55, y+52+i*26), line[:55], font=f_small, fill=WHITE)

    path = "/tmp/briefing.png"
    img.save(path)
    return path

def upload_to_imgbb(image_path):
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_API_KEY, "image": encoded}
    )
    result = r.json()
    if result.get("success"):
        url = result["data"]["url"]
        print(f"이미지 업로드 성공: {url}")
        return url
    else:
        print(f"이미지 업로드 실패: {result}")
        return None

def send_kakao_image(image_url, token):
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "template_object": json.dumps({
            "object_type": "feed",
            "content": {
                "title": f"📊 {now.strftime('%Y.%m.%d')} 아침 시장 브리핑",
                "description": "매일 오전 7시 자동 발송",
                "image_url": image_url,
                "image_width": 800,
                "image_height": 1050,
                "link": {"web_url": "https://finance.naver.com"}
            }
        }, ensure_ascii=False)
    }
    r = requests.post(url, headers=headers, data=data)
    if r.status_code == 200:
        print("이미지 메시지 전송 성공!")
    else:
        print(f"이미지 전송 실패: {r.text}")

def send_kakao_text(text, token):
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {token}"}
    chunks = []
    lines = text.split('\n')
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 800:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        chunks.append(current.strip())
    for i, chunk in enumerate(chunks):
        data = {
            "template_object": json.dumps({
                "object_type": "text",
                "text": chunk,
                "link": {"web_url": "https://finance.naver.com"}
            }, ensure_ascii=False)
        }
        r = requests.post(url, headers=headers, data=data)
        if r.status_code == 200:
            print(f"텍스트 메시지 {i+1}/{len(chunks)} 전송 성공!")
        else:
            print(f"전송 실패: {r.text}")

def main():
    print("토큰 갱신 중...")
    token = refresh_kakao_token()

    print("데이터 수집 중...")
    market_data = get_market_data()
    news = get_news()
    print("AI 분석 중...")
    analysis = get_ai_analysis(market_data, news)

    print(market_data)
    print(analysis)

    # 이미지 생성 및 전송
    if IMGBB_API_KEY:
        print("이미지 생성 중...")
        image_path = make_briefing_image(market_data, analysis)
        image_url = upload_to_imgbb(image_path)
        if image_url:
            send_kakao_image(image_url, token)
        else:
            print("이미지 업로드 실패, 텍스트로 전송")
            send_kakao_text(analysis, token)
    else:
        print("IMGBB_API_KEY 없음, 텍스트로 전송")
        send_kakao_text(analysis, token)

    # AI 분석은 항상 텍스트로도 전송
    send_kakao_text(analysis, token)

if __name__ == "__main__":
    main()