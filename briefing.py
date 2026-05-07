from dotenv import load_dotenv
import os
load_dotenv()

import yfinance as yf
import requests
import json
from datetime import datetime, timedelta
import anthropic
import pytz

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

SECTORS = ["반도체", "AI", "정유", "선박", "해운", "물류", "원자재", "AI전력"]

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

    all_titles = []

    queries_ko = [
        "미국증시 OR 나스닥 OR 월가 OR S&P500",
        "반도체 OR 삼성전자 OR SK하이닉스 OR TSMC",
        "AI OR 인공지능 OR 엔비디아",
        "해운 OR 선박 OR 물류 OR HMM",
        "정유 OR 유가 OR 원유 OR 에너지",
        "AI전력 OR 데이터센터 전력 OR 변압기 OR HD현대일렉트릭 OR 효성중공업",
    ]

    queries_en = [
        "NASDAQ OR S&P500 OR Wall Street",
        "semiconductor OR TSMC OR Nvidia OR memory chip",
        "AI OR artificial intelligence OR OpenAI",
        "shipping OR logistics OR freight",
        "oil price OR crude oil OR energy",
        "AI power demand OR data center energy OR power grid",
    ]

    for query in queries_ko:
        try:
            url = (
                f"https://newsapi.org/v2/everything"
                f"?q={query}"
                f"&language=ko"
                f"&from={yesterday}"
                f"&to={today}"
                f"&pageSize=3"
                f"&sortBy=publishedAt"
                f"&apiKey={NEWSAPI_KEY}"
            )
            r = requests.get(url)
            articles = r.json().get("articles", [])
            all_titles += [a["title"] for a in articles[:2]]
        except:
            pass

    for query in queries_en:
        try:
            url = (
                f"https://newsapi.org/v2/everything"
                f"?q={query}"
                f"&language=en"
                f"&from={yesterday}"
                f"&to={today}"
                f"&pageSize=2"
                f"&sortBy=publishedAt"
                f"&apiKey={NEWSAPI_KEY}"
            )
            r = requests.get(url)
            articles = r.json().get("articles", [])
            all_titles += [a["title"] for a in articles[:1]]
        except:
            pass

    seen = set()
    result = []
    for t in all_titles:
        if t not in seen:
            seen.add(t)
            result.append(t)

    return result[:15]

def get_ai_analysis(market_data, news_headlines):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today_str = now.strftime("%Y년 %m월 %d일")
    data_str = json.dumps(market_data, ensure_ascii=False)
    news_str = "\n".join([f"- {n}" for n in news_headlines])
    sectors_str = ", ".join(SECTORS)

    prompt = f"""당신은 경력 15년의 국내 증권사 수석 애널리스트입니다.
오늘 날짜는 {today_str}이며, 지금은 아침 장 시작 전입니다.
아래는 전날 마감된 시장 데이터와 간밤에 나온 주요 뉴스입니다.
뉴스는 한국어와 영어가 섞여있을 수 있으나 반드시 모든 내용을 한국어로만 작성해주세요.
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
- 예상 코스피 지수 범위 (반드시 숫자로 예: 7,300~7,450p)

💬 한줄 총평"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def send_kakao_text(text, token):
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {token}"}

    chunks = []
    lines = text.split('\n')
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 1000:
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
            print(f"메시지 {i+1}/{len(chunks)} 전송 성공!")
        else:
            print(f"전송 실패: {r.text}")

def main():
    today = now.strftime("%Y.%m.%d (%a)")
    yesterday = (now - timedelta(days=1)).strftime("%m.%d")
    print("토큰 갱신 중...")
    token = refresh_kakao_token()

    print("데이터 수집 중...")
    market_data = get_market_data()
    news = get_news()
    print("AI 분석 중...")
    analysis = get_ai_analysis(market_data, news)

    msg1 = f"""📊 {today} 아침 시장 브리핑

🇺🇸 미국 증시 ({yesterday} 마감)
나스닥: {market_data['나스닥']}
S&P500: {market_data['S&P500']}

📈 국내 증시 (전일 종가)
코스피: {market_data['코스피']}
코스닥: {market_data['코스닥']}

💼 주요 종목 (전일 종가)
삼성전자: {market_data['삼성전자']}
SK하이닉스: {market_data['SK하이닉스']}
네이버: {market_data['네이버']}
라인야후: {market_data['라인야후']}
애플: {market_data['애플']}
테슬라: {market_data['테슬라']}
구글: {market_data['구글']}

💱 환율 / 유가
원/달러: {market_data['원/달러']}
WTI유가: {market_data['WTI유가']}"""

    print(msg1)
    print("\n--- AI 분석 ---")
    print(analysis)

    send_kakao_text(msg1, token)
    send_kakao_text(analysis, token)

if __name__ == "__main__":
    main()