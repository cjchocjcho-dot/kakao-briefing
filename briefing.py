
from dotenv import load_dotenv
import os
load_dotenv()

import yfinance as yf
import requests
import json
from datetime import datetime, timedelta
import anthropic

# ===== 설정 =====
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")

SECTORS = ["반도체", "AI", "정유", "선박", "해운", "물류", "원자재"]

TICKERS = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "네이버": "035420.KS",
    "라인야후": "4689.T",
    "애플": "AAPL",
    "테슬라": "TSLA",
    "구글": "GOOGL",
    "코스피": "^KS11",
    "코스닥": "^KQ11",
    "나스닥": "^IXIC",
    "S&P500": "^GSPC",
    "원/달러": "KRW=X",
    "WTI유가": "CL=F",
}

def get_market_data():
    result = {}
    for name, ticker in TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if len(hist) >= 3:
                prev = float(hist["Close"].iloc[-3])
                curr = float(hist["Close"].iloc[-2])
                change = (curr - prev) / prev * 100
                arrow = "▲" if change > 0 else "▼"
                result[name] = f"{curr:,.1f} {arrow}{abs(change):.1f}%"
            else:
                result[name] = "데이터없음"
        except:
            result[name] = "오류"
    return result

def get_news():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

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
    today = datetime.now().strftime("%Y년 %m월 %d일")
    data_str = json.dumps(market_data, ensure_ascii=False)
    news_str = "\n".join([f"- {n}" for n in news_headlines])
    sectors_str = ", ".join(SECTORS)

    prompt = f"""당신은 경력 15년의 국내 증권사 수석 애널리스트입니다.
오늘 날짜는 {today}이며, 지금은 아침 장 시작 전입니다.
아래는 전날 마감된 시장 데이터와 간밤에 나온 주요 뉴스입니다.
이를 바탕으로 오늘 코스피 시장을 전망하는 브리핑을 작성해주세요.

[전일 마감 시장 데이터]
{data_str}

[간밤 주요 뉴스]
{news_str}

[관심 섹터]
{sectors_str}

반드시 아래 형식으로만 작성해주세요. 제목이나 날짜는 따로 쓰지 마세요:

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
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def send_kakao(text):
    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
    headers = {"Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}"}

    chunks = []
    lines = text.split('\n')
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > 400:
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
    today = datetime.now().strftime("%Y.%m.%d (%a)")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%m.%d")
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

    msg2 = analysis

    print(msg1)
    print("\n--- AI 분석 ---")
    print(msg2)

    send_kakao(msg1)
    send_kakao(msg2)

if __name__ == "__main__":
    main()