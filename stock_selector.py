import requests
from bs4 import BeautifulSoup
import pandas as pd
from konlpy.tag import Okt
from collections import Counter
import re
import random

# --- 1. 뉴스 수집 모듈 (Naver News) ---
def get_naver_news_headlines(query="주식", num_articles=10):
    """네이버 뉴스에서 헤드라인을 수집합니다."""
    base_url = "https://search.naver.com/search.naver"
    all_articles = []
    
    # 긍정적인 분야를 찾기 위해 '성장', '기술', '투자', '실적' 등의 키워드를 사용
    search_queries = [f"{query} 성장", f"{query} 기술", f"{query} 투자", f"{query} 실적"]
    
    for q in search_queries:
        params = {
            "where": "news",
            "query": q,
            "sort": "1",  # 1: 최신순
            "start": "1"
        }
        
        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            news_items = soup.select('div.news_area')
            
            for item in news_items:
                title = item.select_one('a.news_tit')['title'] if item.select_one('a.news_tit') else None
                snippet = item.select_one('div.news_dsc').text.strip() if item.select_one('div.news_dsc') else None
                link = item.select_one('a.news_tit')['href'] if item.select_one('a.news_tit') else None
                
                if title and snippet:
                    all_articles.append({
                        "query": q,
                        "title": title,
                        "snippet": snippet,
                        "link": link
                    })
                
                if len(all_articles) >= num_articles:
                    break
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching news for query '{q}': {e}")
            continue

    return all_articles

# --- 2. 감성 분석 및 분야 추출 모듈 ---
# Konlpy를 사용하여 명사 추출 및 간단한 감성 분석 수행
okt = Okt()

# 긍정적인 키워드 리스트 (사용자 정의)
POSITIVE_KEYWORDS = ["성장", "기술", "혁신", "투자", "수주", "실적", "상승", "돌파", "확대", "개선", "호재", "수혜"]

def analyze_sentiment_and_sector(articles):
    """기사 제목과 내용에서 긍정적인 키워드를 분석하고 분야를 추출합니다."""
    sector_keywords = []
    
    for article in articles:
        text = article['title'] + " " + article['snippet']
        
        # 1. 긍정 키워드 포함 여부 확인
        is_positive = any(keyword in text for keyword in POSITIVE_KEYWORDS)
        
        if is_positive:
            # 2. 명사 추출 (분야/종목 관련 키워드 추출)
            nouns = okt.nouns(text)
            
            # 3. 불용어 제거 및 분야 키워드 필터링 (예시)
            filtered_nouns = [
                n for n in nouns 
                if len(n) > 1 and n not in ["주식", "투자", "종목", "기업", "증시", "시장", "금융", "뉴스", "이날", "전망", "분석"]
            ]
            
            sector_keywords.extend(filtered_nouns)

    # 가장 많이 언급된 상위 5개 키워드 (분야) 추출
    sector_counts = Counter(sector_keywords).most_common(5)
    
    print("\n[감성 분석 결과]")
    print(f"총 {len(articles)}개 기사 분석 완료")
    print(f"긍정 키워드: {POSITIVE_KEYWORDS}")
    print("-----------------------------------")
    print("주요 긍정 분야 키워드 (Top 5):")
    for keyword, count in sector_counts:
        print(f"- {keyword}: {count}회 언급")
        
    return [item[0] for item in sector_counts]

# --- 3. 종목 매핑 및 선정 모듈 (모의 데이터 사용) ---
# 실제 API 연동이 없으므로, 임의의 종목 데이터베이스를 사용합니다.
MOCK_STOCK_DB = {
    "반도체": [("삼성전자", "005930", 8000000), ("SK하이닉스", "000660", 5000000), ("DB하이텍", "000990", 1000000)],
    "AI": [("솔트룩스", "340760", 500000), ("셀바스AI", "390000", 400000), ("이스트소프트", "000000", 300000)],
    "2차전지": [("LG에너지솔루션", "373220", 9000000), ("삼성SDI", "006400", 7000000), ("에코프로비엠", "247540", 6000000)],
    "바이오": [("삼성바이오로직스", "207940", 12000000), ("셀트리온", "068270", 6000000), ("한미약품", "128940", 4000000)],
    "로봇": [("두산로보틱스", "454910", 800000), ("레인보우로보틱스", "277810", 700000), ("유진로봇", "056080", 300000)]
}

def select_top_stocks(sector_keywords, max_stocks=5):
    """추출된 분야 키워드를 기반으로 상위 종목을 선정합니다."""
    candidate_stocks = []
    
    print("\n[종목 선정 과정]")
    print("-----------------------------------")
    
    for keyword in sector_keywords:
        # 키워드와 매핑되는 종목이 있는지 확인
        if keyword in MOCK_STOCK_DB:
            # 시가총액(세 번째 요소) 기준으로 정렬하여 상위 종목 선택
            sorted_stocks = sorted(MOCK_STOCK_DB[keyword], key=lambda x: x[2], reverse=True)
            
            print(f"분야 '{keyword}'에서 상위 종목을 추출합니다.")
            
            # 각 분야에서 1~2개 종목을 선택하여 최대 5개 종목을 맞춥니다.
            for stock in sorted_stocks[:2]:
                if len(candidate_stocks) < max_stocks and stock not in candidate_stocks:
                    candidate_stocks.append(stock)
                
    # 최종 5개 종목을 무작위로 선택 (5개 미만일 경우 그대로 사용)
    if len(candidate_stocks) > max_stocks:
        final_stocks = random.sample(candidate_stocks, max_stocks)
    else:
        final_stocks = candidate_stocks

    print(f"\n[최종 선정 종목 (최대 {max_stocks}개)]")
    for name, code, market_cap in final_stocks:
        print(f"- {name} ({code}) - 시총: {market_cap:,}억원")
        
    return final_stocks

# --- 4. 재무/기술적 분석 모듈 (모의 데이터 사용) ---
def mock_analyze_stock(stock_list):
    """선정된 종목에 대해 재무 및 기술적 분석을 수행합니다. (모의 데이터)"""
    analyzed_results = []
    
    print("\n[재무 및 기술적 분석 (모의)]")
    print("-----------------------------------")
    
    for name, code, market_cap in stock_list:
        # 모의 재무 데이터 (워렌 버핏 기준 적용)
        mock_roe = random.uniform(10, 20) # ROE 15% 이상이면 가산점
        mock_debt_ratio = random.uniform(50, 150) # 부채비율 100% 이하이면 가산점
        mock_eps_growth = random.uniform(0.05, 0.20) # EPS 성장률

        # 모의 기술적 데이터 (5가지 지표)
        mock_ma_alignment = random.choice(["정배열", "역배열"]) # 정배열이면 가산점
        mock_rsi = random.uniform(30, 70) # 70 이하이면 가산점
        mock_macd_signal = random.choice(["상향돌파", "하향이탈"]) # 상향돌파면 가산점
        mock_volume_ratio = random.uniform(1.0, 2.0) # 1.5 이상이면 가산점
        mock_bb_position = random.choice(["상단돌파직전", "중앙", "하단"]) # 상단돌파직전이면 가산점
        
        analyzed_results.append({
            "name": name,
            "code": code,
            "market_cap": market_cap,
            "재무_ROE": mock_roe,
            "재무_부채비율": mock_debt_ratio,
            "재무_EPS성장률": mock_eps_growth,
            "기술_MA배열": mock_ma_alignment,
            "기술_RSI": mock_rsi,
            "기술_MACD": mock_macd_signal,
            "기술_거래량비율": mock_volume_ratio,
            "기술_BB위치": mock_bb_position
        })
        
        print(f"- {name} 분석 완료 (ROE: {mock_roe:.2f}%, 부채비율: {mock_debt_ratio:.2f}%)")
        
    return analyzed_results

# --- 5. 매매 판단 및 점수화 모듈 (전문가 기법 적용) ---
def score_stocks(analysis_data, total_investment=10000000):
    """
    전문가 기법을 적용하여 종목별 점수를 계산하고, 매수 판단 및 금액을 설정합니다.
    total_investment: 총 투자 가능 금액 (예시로 1000만원 설정)
    """
    scored_results = []
    
    print("\n[5. 매매 판단 및 점수화 (전문가 기법 적용)]")
    print("-----------------------------------")
    
    for stock in analysis_data:
        score = 0
        reasons = []
        
        # 1. 워렌 버핏 (가치 투자) - 최대 2점
        if stock['재무_ROE'] >= 15.0:
            score += 1
            reasons.append("버핏-ROE(15% 이상): +1점")
        if stock['재무_부채비율'] <= 100.0:
            score += 1
            reasons.append("버핏-부채비율(100% 이하): +1점")
            
        # 2. 피터 린치 (성장주 투자) - 최대 2점
        # PEG Ratio 1.0 이하 (모의: EPS 성장률 10% 이상)
        if stock['재무_EPS성장률'] >= 0.10:
            score += 2
            reasons.append("린치-EPS성장(10% 이상): +2점")
            
        # 3. 제시 리버모어 (추세 매매) - 최대 3점
        # 52주 신고가 근접 (모의: 볼린저밴드 상단돌파직전)
        if stock['기술_BB위치'] == "상단돌파직전":
            score += 2
            reasons.append("리버모어-추세(BB 상단직전): +2점")
        # 거래량 폭발 (모의: 거래량비율 1.5 이상)
        if stock['기술_거래량비율'] >= 1.5:
            score += 1
            reasons.append("리버모어-거래량(1.5배 이상): +1점")

        # 4. 기술적 우위 (보조 지표) - 최대 2점
        if stock['기술_MA배열'] == "정배열":
            score += 1
            reasons.append("기술-정배열: +1점")
        if stock['기술_RSI'] <= 70.0:
            score += 1
            reasons.append("기술-RSI(70 이하): +1점")
            
        # 매수 판단
        buy_decision = "매수" if score >= 4 else "관망"
        
        # 금액 설정 (총 투자금의 1/3 분할 매수)
        investment_amount = total_investment / 3 if buy_decision == "매수" else 0
        
        # 목표가 설정 (매수 시점 대비 +5% 수익률)
        # 실제 매매에서는 현재가 정보를 가져와야 함. 여기서는 모의로 10000원으로 가정
        mock_current_price = random.randint(10000, 50000)
        target_price = mock_current_price * 1.05 if buy_decision == "매수" else 0
        
        scored_results.append({
            "name": stock['name'],
            "code": stock['code'],
            "score": score,
            "decision": buy_decision,
            "investment_amount": investment_amount,
            "target_price": target_price,
            "reasons": ", ".join(reasons)
        })
        
        print(f"- {stock['name']} (점수: {score}점) -> {buy_decision} 결정 (금액: {investment_amount:,}원)")
        
    # 최종 매수 종목 선정 (점수 상위 3개)
    final_buy_list = sorted(
        [s for s in scored_results if s['decision'] == "매수"], 
        key=lambda x: x['score'], 
        reverse=True
    )[:3]
    
    print("\n[최종 매매 대상 종목 (점수 상위 3개)]")
    for stock in final_buy_list:
        print(f"-> {stock['name']} (점수: {stock['score']}점, 목표가: {stock['target_price']:.0f}원)")
        
    return final_buy_list

# --- 메인 실행 함수 ---
def run_stock_selection_prototype():
    print("--- 주식 자동매매 종목 선정 프로토타입 실행 ---")
    
    # 1. 뉴스 수집 (실패 시 모의 데이터 사용)
    articles = get_naver_news_headlines()
    if not articles:
        print("뉴스 수집에 실패했습니다. 모의 데이터를 사용하여 분석 로직을 테스트합니다.")
        # 모의 뉴스 데이터 생성
        articles = [
            {"title": "삼성전자, AI 반도체 기술 혁신으로 주가 상승 기대", "snippet": "차세대 AI 칩 개발에 성공하며 시장의 주목을 받고 있습니다."},
            {"title": "LG에너지솔루션, 유럽 대규모 수주로 실적 확대 전망", "snippet": "글로벌 전기차 시장 성장에 힘입어 2차전지 분야의 호재가 이어지고 있습니다."},
            {"title": "두산로보틱스, 협동 로봇 시장 선점 가속화", "snippet": "산업용 로봇 기술 개발에 집중하며 미래 성장 동력을 확보하고 있습니다."},
            {"title": "SK하이닉스, 고성능 메모리 기술 개발 성공", "snippet": "반도체 업계의 기술 경쟁에서 우위를 점하며 투자 심리가 개선되고 있습니다."},
            {"title": "셀트리온, 신약 개발 임상 3상 성공 소식", "snippet": "바이오 분야의 기대감이 높아지며 주가에 긍정적인 영향을 미칠 것으로 예상됩니다."}
        ]
        if not articles:
            print("모의 데이터 생성에도 실패했습니다. 프로토타입을 종료합니다.")
            return

    # 2. 감성 분석 및 분야 추출
    top_sectors = analyze_sentiment_and_sector(articles)
    
    if not top_sectors:
        print("긍정적인 분야 키워드를 추출하지 못했습니다. 프로토타입을 종료합니다.")
        return

    # 3. 종목 선정
    selected_stocks = select_top_stocks(top_sectors)
    
    if not selected_stocks:
        print("선정된 종목이 없습니다. 프로토타입을 종료합니다.")
        return

    # 4. 재무/기술적 분석
    final_analysis = mock_analyze_stock(selected_stocks)
    
    # 5. 매매 판단 및 점수화
    final_decisions = score_stocks(final_analysis)
    
    print("\n--- 최종 분석 및 매매 결정 (DataFrame) ---")
    # 분석 데이터와 결정 데이터를 병합하여 출력
    df_analysis = pd.DataFrame(final_analysis)
    df_decisions = pd.DataFrame(final_decisions)
    
    if not df_decisions.empty:
        # 결정된 종목만 필터링하여 출력
        df_merged = pd.merge(df_analysis, df_decisions[['name', 'score', 'decision', 'investment_amount', 'target_price', 'reasons']], on='name', how='inner')
        print(df_merged.to_markdown(index=False))
        return df_merged
    else:
        print("최종 매수 결정된 종목이 없습니다.")
        print(df_analysis.to_markdown(index=False))
        return df_analysis

if __name__ == "__main__":
    run_stock_selection_prototype()
