import os
import requests
import json
from dotenv import load_dotenv

# .env 환경변수 로드
load_dotenv()

class TossInvestAPI:
    def __init__(self):
        self.base_url = "https://openapi.tossinvest.com"
        self.api_key = os.getenv("TOSS_API_KEY", "")
        self.secret_key = os.getenv("TOSS_SECRET_KEY", "")
        self.account_seq = os.getenv("TOSS_ACCOUNT_SEQ", "1")
        self.access_token = None

    def get_headers(self):
        """기본 API 요청 헤더 생성"""
        headers = {
            "Content-Type": "application/json",
            "apiKey": self.api_key
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def issue_token(self):
        """토스증권 OAuth2 Access Token 발급/갱신"""
        url = f"{self.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token")
                return True, "토큰 발급 성공"
            return False, f"인증 실패 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"네트워크 통신 오류: {str(e)}"

    def get_price(self, symbol: str):
        """국내/미국 주식 현재가 및 시세 정보 조회 (예: '005930', 'AAPL')"""
        url = f"{self.base_url}/v1/market/quote"
        params = {"symbol": symbol}
        try:
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=10)
            if resp.status_code == 200:
                return True, resp.json()
            return False, f"조회 실패 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"통신 오류: {str(e)}"

    def get_balance(self):
        """계좌 예수금 및 보유 주식 잔고 조회"""
        url = f"{self.base_url}/v1/accounts/{self.account_seq}/balance"
        try:
            resp = requests.get(url, headers=self.get_headers(), timeout=10)
            if resp.status_code == 200:
                return True, resp.json()
            return False, f"잔고 조회 실패 (HTTP {resp.status_code}): {resp.text}"
        except Exception as e:
            return False, f"통신 오류: {str(e)}"

if __name__ == "__main__":
    print("[toss_api.py] 모듈 로드 완료. API 키 입력 대기 상태입니다.")
