from flask import Flask, jsonify, request
import pandas as pd
import json
import os

# stock_selector.py에서 필요한 함수들을 import
# 실제 환경에서는 모듈로 분리하여 import 해야 하지만, 여기서는 편의상 동일 파일에 있다고 가정
# from stock_selector import run_stock_selection_prototype 

# 임시로 run_stock_selection_prototype 함수를 호출하는 모의 함수 정의
def run_stock_selection_prototype():
    """
    모의 종목 선정 결과를 DataFrame 형태로 반환하는 함수
    실제로는 stock_selector.py의 로직이 실행됨
    """
    # 5단계 실행 결과의 DataFrame을 그대로 사용 (실제 로직 실행 대신)
    data = {
        'name': ['두산로보틱스', '레인보우로보틱스', '삼성전자'],
        'code': ['454910', '277810', '005930'],
        'market_cap': [800000, 700000, 8000000],
        '재무_ROE': [16.5536, 14.2795, 18.6192],
        '재무_부채비율': [126.321, 129.191, 132.219],
        '재무_EPS성장률': [0.140701, 0.196174, 0.0695394],
        '기술_MA배열': ['정배열', '역배열', '정배열'],
        '기술_RSI': [41.0057, 40.2287, 32.6847],
        '기술_MACD': ['하향이탈', '하향이탈', '하향이탈'],
        '기술_거래량비율': [1.56149, 1.98826, 1.54118],
        '기술_BB위치': ['하단', '상단돌파직전', '하단'],
        'score': [6, 6, 4],
        'decision': ['매수', '매수', '매수'],
        'investment_amount': [3333333.33, 3333333.33, 3333333.33],
        'target_price': [44492, 33470, 45917],
        'reasons': [
            '버핏-ROE(15% 이상): +1점, 린치-EPS성장(10% 이상): +2점, 리버모어-거래량(1.5배 이상): +1점, 기술-정배열: +1점, 기술-RSI(70 이하): +1점',
            '린치-EPS성장(10% 이상): +2점, 리버모어-추세(BB 상단직전): +2점, 리버모어-거래량(1.5배 이상): +1점, 기술-RSI(70 이하): +1점',
            '버핏-ROE(15% 이상): +1점, 리버모어-거래량(1.5배 이상): +1점, 기술-정배열: +1점, 기술-RSI(70 이하): +1점'
        ]
    }
    return pd.DataFrame(data)

app = Flask(__name__)

@app.route('/api/select_stocks', methods=['GET'])
def select_stocks():
    """
    뉴스 수집, 분석, 종목 선정 및 매매 판단 로직을 실행하고 결과를 반환하는 엔드포인트
    """
    try:
        # 실제 로직 실행
        df_result = run_stock_selection_prototype()
        
        # DataFrame을 JSON 형태로 변환
        result_json = df_result.to_json(orient='records', force_ascii=False)
        
        return jsonify({
            "status": "success",
            "message": "종목 선정 및 매매 판단이 완료되었습니다.",
            "data": json.loads(result_json)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"종목 선정 중 오류 발생: {str(e)}"
        }), 500

@app.route('/api/execute_trade', methods=['POST'])
def execute_trade():
    """
    선정된 종목에 대해 실제 매매 주문을 실행하는 엔드포인트 (모의)
    """
    data = request.get_json()
    if not data or 'code' not in data or 'amount' not in data:
        return jsonify({"status": "error", "message": "종목 코드와 금액이 필요합니다."}), 400

    stock_code = data['code']
    amount = data['amount']
    
    # TODO: 여기에 한국투자증권 API를 통한 실제 주문 로직 구현
    # 현재는 모의 주문 실행으로 대체
    
    # KIS API 연동을 위한 환경 변수 확인 (보안상 실제 키는 입력하지 않음)
    app_key = os.environ.get("KIS_APP_KEY", "모의_APP_KEY_없음")
    app_secret = os.environ.get("KIS_APP_SECRET", "모의_SECRET_KEY_없음")

    trade_result = {
        "status": "success",
        "message": f"[{stock_code}] {amount:,}원 매수 주문이 모의 환경에서 접수되었습니다.",
        "details": {
            "stock_code": stock_code,
            "order_amount": amount,
            "api_key_status": "OK" if app_key != "모의_APP_KEY_없음" else "미설정"
        }
    }
    
    return jsonify(trade_result)

if __name__ == '__main__':
    # 개발 서버 실행 (외부 접근을 위해 host='0.0.0.0' 설정)
    # n8n에서 호출할 수 있도록 포트 5000을 사용
    app.run(host='0.0.0.0', port=5000)
