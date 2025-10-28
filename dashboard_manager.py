import pandas as pd
from datetime import datetime
import json

class DashboardManager:
    """
    Google Sheets 대시보드를 관리하고 결과를 정산하는 클래스
    """
    
    def __init__(self):
        """대시보드 매니저 초기화"""
        self.trade_log = []
        self.portfolio = {}
        self.daily_summary = {}
        
    def record_trade(self, stock_name, stock_code, investment_amount, target_price, current_price=None):
        """
        매매 거래를 기록합니다.
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드
            investment_amount: 투자 금액
            target_price: 목표가
            current_price: 현재가 (선택사항)
        """
        trade_record = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock_name": stock_name,
            "stock_code": stock_code,
            "investment_amount": investment_amount,
            "target_price": target_price,
            "current_price": current_price if current_price else target_price,
            "status": "주문접수"
        }
        
        self.trade_log.append(trade_record)
        print(f"✓ 거래 기록: {stock_name} ({stock_code}) - {investment_amount:,}원")
        
        return trade_record
    
    def update_portfolio(self, stock_name, stock_code, buy_price, quantity, current_price=None):
        """
        포트폴리오를 업데이트합니다.
        
        Args:
            stock_name: 종목명
            stock_code: 종목코드
            buy_price: 매수가
            quantity: 수량
            current_price: 현재가 (선택사항)
        """
        if stock_code not in self.portfolio:
            self.portfolio[stock_code] = {
                "stock_name": stock_name,
                "buy_price": buy_price,
                "quantity": quantity,
                "current_price": current_price if current_price else buy_price,
                "purchase_date": datetime.now().strftime("%Y-%m-%d")
            }
        else:
            # 기존 보유 종목이면 평균 단가 계산
            existing = self.portfolio[stock_code]
            total_quantity = existing["quantity"] + quantity
            avg_price = (existing["buy_price"] * existing["quantity"] + buy_price * quantity) / total_quantity
            existing["buy_price"] = avg_price
            existing["quantity"] = total_quantity
            existing["current_price"] = current_price if current_price else buy_price
        
        print(f"✓ 포트폴리오 업데이트: {stock_name} ({stock_code}) - {quantity}주")
    
    def calculate_profit_loss(self, stock_code):
        """
        특정 종목의 손익을 계산합니다.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            dict: 손익 정보 (수익/손실액, 수익률)
        """
        if stock_code not in self.portfolio:
            return None
        
        holding = self.portfolio[stock_code]
        profit_loss = (holding["current_price"] - holding["buy_price"]) * holding["quantity"]
        profit_rate = ((holding["current_price"] - holding["buy_price"]) / holding["buy_price"]) * 100
        
        return {
            "stock_code": stock_code,
            "stock_name": holding["stock_name"],
            "profit_loss": profit_loss,
            "profit_rate": profit_rate,
            "evaluation_amount": holding["current_price"] * holding["quantity"]
        }
    
    def calculate_total_profit_loss(self):
        """
        전체 포트폴리오의 손익을 계산합니다.
        
        Returns:
            dict: 전체 손익 정보
        """
        total_profit_loss = 0
        total_evaluation = 0
        total_investment = 0
        
        for stock_code, holding in self.portfolio.items():
            profit_loss = (holding["current_price"] - holding["buy_price"]) * holding["quantity"]
            total_profit_loss += profit_loss
            total_evaluation += holding["current_price"] * holding["quantity"]
            total_investment += holding["buy_price"] * holding["quantity"]
        
        total_profit_rate = (total_profit_loss / total_investment * 100) if total_investment > 0 else 0
        
        return {
            "total_investment": total_investment,
            "total_evaluation": total_evaluation,
            "total_profit_loss": total_profit_loss,
            "total_profit_rate": total_profit_rate,
            "holding_count": len(self.portfolio)
        }
    
    def generate_dashboard_summary(self):
        """
        대시보드 요약 정보를 생성합니다.
        
        Returns:
            dict: 대시보드 요약 정보
        """
        total_info = self.calculate_total_profit_loss()
        
        summary = {
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "today_trade_count": len([t for t in self.trade_log if t["date"].startswith(datetime.now().strftime("%Y-%m-%d"))]),
            "total_investment": total_info["total_investment"],
            "holding_count": total_info["holding_count"],
            "total_profit_loss": total_info["total_profit_loss"],
            "cumulative_profit_rate": total_info["total_profit_rate"],
            "today_profit_rate": self._calculate_today_profit_rate()
        }
        
        return summary
    
    def _calculate_today_profit_rate(self):
        """오늘의 수익률을 계산합니다."""
        today_trades = [t for t in self.trade_log if t["date"].startswith(datetime.now().strftime("%Y-%m-%d"))]
        if not today_trades:
            return 0.0
        
        total_today_investment = sum(t["investment_amount"] for t in today_trades)
        total_today_profit = sum((t["current_price"] - t["target_price"]) * (t["investment_amount"] / t["target_price"]) for t in today_trades)
        
        return (total_today_profit / total_today_investment * 100) if total_today_investment > 0 else 0.0
    
    def get_portfolio_dataframe(self):
        """
        포트폴리오를 DataFrame 형태로 반환합니다.
        
        Returns:
            pd.DataFrame: 포트폴리오 정보
        """
        portfolio_data = []
        
        for stock_code, holding in self.portfolio.items():
            profit_loss_info = self.calculate_profit_loss(stock_code)
            portfolio_data.append({
                "종목명": holding["stock_name"],
                "종목코드": stock_code,
                "매수가": holding["buy_price"],
                "수량": holding["quantity"],
                "현재가": holding["current_price"],
                "평가금액": profit_loss_info["evaluation_amount"],
                "수익/손실": profit_loss_info["profit_loss"],
                "수익률(%)": profit_loss_info["profit_rate"]
            })
        
        return pd.DataFrame(portfolio_data)
    
    def get_trade_log_dataframe(self):
        """
        거래 로그를 DataFrame 형태로 반환합니다.
        
        Returns:
            pd.DataFrame: 거래 로그
        """
        return pd.DataFrame(self.trade_log)
    
    def export_to_json(self, filename="dashboard_data.json"):
        """
        대시보드 데이터를 JSON 파일로 내보냅니다.
        
        Args:
            filename: 저장할 파일명
        """
        data = {
            "summary": self.generate_dashboard_summary(),
            "portfolio": self.get_portfolio_dataframe().to_dict(orient='records'),
            "trade_log": self.get_trade_log_dataframe().to_dict(orient='records')
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 대시보드 데이터가 {filename}으로 저장되었습니다.")
    
    def print_dashboard_summary(self):
        """대시보드 요약을 콘솔에 출력합니다."""
        summary = self.generate_dashboard_summary()
        
        print("\n" + "="*60)
        print("📊 투자 성과 대시보드 요약")
        print("="*60)
        print(f"마지막 업데이트: {summary['last_update']}")
        print(f"오늘 매매 건수: {summary['today_trade_count']}건")
        print(f"총 투자 금액: {summary['total_investment']:,.0f}원")
        print(f"현재 보유 종목 수: {summary['holding_count']}개")
        print(f"누적 수익률: {summary['cumulative_profit_rate']:+.2f}%")
        print(f"오늘 수익률: {summary['today_profit_rate']:+.2f}%")
        print("="*60 + "\n")
    
    def print_portfolio(self):
        """포트폴리오를 콘솔에 출력합니다."""
        df = self.get_portfolio_dataframe()
        
        print("\n" + "="*100)
        print("💼 보유 종목 현황")
        print("="*100)
        print(df.to_string(index=False))
        print("="*100 + "\n")


# 테스트 코드
if __name__ == "__main__":
    # 대시보드 매니저 인스턴스 생성
    dashboard = DashboardManager()
    
    print("--- 투자 성과 대시보드 테스트 ---\n")
    
    # 거래 기록
    dashboard.record_trade("두산로보틱스", "454910", 3333333, 44492, 43000)
    dashboard.record_trade("레인보우로보틱스", "277810", 3333333, 33470, 32500)
    dashboard.record_trade("삼성전자", "005930", 3333333, 45917, 44500)
    
    # 포트폴리오 업데이트
    dashboard.update_portfolio("두산로보틱스", "454910", 43000, 77, 43500)
    dashboard.update_portfolio("레인보우로보틱스", "277810", 32500, 102, 33000)
    dashboard.update_portfolio("삼성전자", "005930", 44500, 74, 45000)
    
    # 대시보드 요약 출력
    dashboard.print_dashboard_summary()
    
    # 포트폴리오 출력
    dashboard.print_portfolio()
    
    # 거래 로그 출력
    print("\n" + "="*100)
    print("📋 거래 로그")
    print("="*100)
    print(dashboard.get_trade_log_dataframe().to_string(index=False))
    print("="*100 + "\n")
    
    # JSON으로 내보내기
    dashboard.export_to_json("/home/ubuntu/dashboard_data.json")

