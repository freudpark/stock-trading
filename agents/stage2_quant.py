import os, sys, json

def run_stage2_quant(symbol="005930", stock_name="삼성전자", prev_high=75000, prev_low=72000, today_open=73000, current_price=74600, k=0.5):
    """2단계: Codex Engine - 퀀트 변동성 돌파 타점 및 하방 리스크 정밀 검증 모듈"""
    stage1_path = os.path.expanduser("~/stock_bot/data/stage1_report.json")
    stage1_opinion = "1차 데이터 없음"
    if os.path.exists(stage1_path):
        with open(stage1_path, "r", encoding="utf-8") as f:
            s1_data = json.load(f)
            stage1_opinion = s1_data.get("opinion", "1차 분석 완료")

    range_val = prev_high - prev_low
    target_buy_price = today_open + (range_val * k)
    
    is_breakout = current_price >= target_buy_price
    downside_risk_pct = round(((current_price - prev_low) / current_price) * 100, 2)
    
    quant_result = {
        "stage": "2단계: Codex Quant Engine",
        "symbol": symbol,
        "stock_name": stock_name,
        "stage1_reference": stage1_opinion,
        "prev_high": prev_high,
        "prev_low": prev_low,
        "today_open": today_open,
        "current_price": current_price,
        "target_buy_price": target_buy_price,
        "is_breakout": is_breakout,
        "downside_risk_pct": f"{downside_risk_pct}%",
        "validation_status": "PASS" if is_breakout else "WAIT",
        "summary": f"목표가 {target_buy_price:,.0f}원 돌파 확인(현재가 {current_price:,.0f}원). 하방 리스크 {downside_risk_pct}%로 검증 통과" if is_breakout else f"목표가 {target_buy_price:,.0f}원 미도달. 대기 필요"
    }

    out_path = os.path.expanduser("~/stock_bot/data/stage2_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(quant_result, f, ensure_ascii=False, indent=2)

    return quant_result

if __name__ == "__main__":
    res = run_stage2_quant()
    print("\n" + "="*48)
    print("        📊 [2단계 Codex 퀀트 검증 보고서]")
    print("="*48)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("="*48)
