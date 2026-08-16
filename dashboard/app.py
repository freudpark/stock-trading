from flask import Flask, jsonify
import datetime, os

app = Flask(__name__)
state = {
    "mode": "MANUAL",
    "account": {"total": "10,540,000원", "cash": "4,200,000원", "profit": "+5.4%", "daily": "+540,000원"},
    "pipeline": {
        "m": {"name": "1단계: MBD Free AI", "st": "완료", "txt": "삼성전자(005930) 호재 뉴스 & 골든크로스"},
        "c": {"name": "2단계: Codex Engine", "st": "완료", "txt": "목표가 74,500원 검증, 리스크 1.2%"},
        "l": {"name": "3단계: Claude Code", "st": "승인 대기", "txt": "1·2차 검증 통과. 20주 매수 승인 요청"}
    },
    "order": {"name": "삼성전자 (005930)", "type": "지정가 매수 / 20주", "price": "74,500원 (총 149만원)"},
    "logs": ["[09:01] 시스템 초기화 완료 - 토스증권 API 연결", "[09:02] [1단계 MBD] 실시간 뉴스 및 시세 수집 완료", "[09:03] [2단계 Codex] 퀀트 변동성 돌파 정밀 검증", "[09:03] [3단계 Claude] 최종 매수 시그널 도출 -> 사용자 승인 대기"]
}

@app.route("/api/state")
def get_state(): return jsonify(state)

@app.route("/api/toggle", methods=["POST"])
def toggle():
    state["mode"] = "AUTO" if state["mode"] == "MANUAL" else "MANUAL"
    state["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 모드 전환 -> {state['mode']}")
    return jsonify({"mode": state["mode"]})

@app.route("/api/approve", methods=["POST"])
def approve():
    if state["order"]:
        state["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 🚀 [매매 승인] {state['order']['name']} 주문 전송 완료")
        state["order"] = None
        state["pipeline"]["l"]["st"] = "주문 완료"
        return jsonify({"msg": "주문이 승인 및 전송되었습니다."})
    return jsonify({"msg": "대기 중인 주문이 없습니다."})

@app.route("/api/reject", methods=["POST"])
def reject():
    if state["order"]:
        state["logs"].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ⛔ [매매 반려] {state['order']['name']} 취소됨")
        state["order"] = None
        state["pipeline"]["l"]["st"] = "반려됨"
        return jsonify({"msg": "주문이 반려되었습니다."})
    return jsonify({"msg": "대기 중인 주문이 없습니다."})

@app.route("/")
def index():
    path = os.path.expanduser("~/stock_bot/dashboard/index.html")
    with open(path, encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
