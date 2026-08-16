import os
import requests
import logging
from dotenv import load_dotenv
from toss_api import TossInvestAPI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

class AutoTrader:
    def __init__(self, target_symbol="005930", target_k=0.5):
        self.api = TossInvestAPI()
        self.target_symbol = target_symbol  # 기본 감시 종목 (예: 삼성전자 005930)
        self.k = target_k                   # 변동성 돌파 계수 (기본 0.5)

    def create_order(self, symbol: str, side: str, order_type: str, quantity: int, price: int = 0):
        """
        주식 주문 실행 함수
        - side: 'BUY'(매수) / 'SELL'(매도)
        - order_type: 'LIMIT'(지정가) / 'MARKET'(시장가)
        """
        url = f"{self.api.base_url}/v1/orders"
        payload = {
            "accountSeq": self.api.account_seq,
            "symbol": symbol,
            "side": side.upper(),
            "orderType": order_type.upper(),
            "quantity": str(quantity)
        }
        if order_type.upper() == "LIMIT":
            payload["price"] = str(price)

        try:
            resp = requests.post(url, headers=self.api.get_headers(), json=payload, timeout=10)
            if resp.status_code == 200:
                logging.info(f"✅ 주문 전송 성공 [{side}]: {symbol} {quantity}주")
                return True, resp.json()
            return False, f"주문 실패 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"주문 통신 오류: {str(e)}"

    def check_volatility_breakout(self, prev_high: float, prev_low: float, today_open: float, current_price: float):
        """
        변동성 돌파 전략 매수 시그널 판단
        - 목표 매수가 = 당일 시가 + (전일 고가 - 전일 저가) * K
        """
        range_val = prev_high - prev_low
        target_buy_price = today_open + (range_val * self.k)
        
        # 현재가가 목표 매수가를 돌파하면 매수 시그널 True
        should_buy = current_price >= target_buy_price
        return should_buy, target_buy_price

if __name__ == "__main__":
    trader = AutoTrader()
    # 1. 샘플 데이터로 전략 계산 검증 (전일고가 75,000 / 전일저가 72,000 / 금일시가 73,000 / 현재가 74,600)
    should_buy, target = trader.check_volatility_breakout(
        prev_high=75000, prev_low=72000, today_open=73000, current_price=74600
    )
    print(f"[전략 연산 테스트] 목표 매수가: {target:,.0f}원 | 현재가: 74,600원 | 매수 시그널: {should_buy}")
