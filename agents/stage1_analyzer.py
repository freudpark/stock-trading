import os, sys, json, requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/stock_bot/.env"))
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

def run_stage1_analysis(symbol="005930", stock_name="삼성전자"):
    """1단계: 실시간 뉴스 및 기초 기술지표 종합 분석 (MBD/무료 AI 모듈)"""
    if not API_KEY:
        return {"status": "ERROR", "message": "GEMINI_API_KEY가 없습니다."}

    prompt = f"""
당신은 1단계 주식 기초 분석 AI 에이전트(MBD Analyzer)입니다.
대상 종목: {stock_name} ({symbol})

다음 항목을 바탕으로 종합 기초 분석 보고서를 작성하세요:
1. 최근 주요 뉴스 및 시장 호재/악재 감성 분석
2. 이동평균선(5일/20일/60일선) 추세 및 수급 상황 요약
3. 1차 매수 타당성 의견 (적극매수 / 관망 / 매도주의)

반드시 아래 JSON 형식으로만 답변하세요:
{{
    "symbol": "{symbol}",
    "stock_name": "{stock_name}",
    "sentiment": "호재(긍정) / 중립 / 악재(부정)",
    "trend": "상승추세 / 횡보 / 하락추세",
    "opinion": "1차 매수 적합 / 관망 추천",
    "summary": "1~2줄 핵심 요약 내용"
}}
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "symbol": {"type": "STRING"},
                    "stock_name": {"type": "STRING"},
                    "sentiment": {"type": "STRING"},
                    "trend": {"type": "STRING"},
                    "opinion": {"type": "STRING"},
                    "summary": {"type": "STRING"}
                },
                "required": ["symbol", "stock_name", "sentiment", "trend", "opinion", "summary"]
            }
        }
    }
    
    print(f"🔍 [1단계 AI] {stock_name}({symbol}) 뉴스 및 기술지표 1차 분석 진행 중...")
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if text.startswith("```"):
                # Strip markdown code block
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            res_json = json.loads(text, strict=False)
            out_path = os.path.expanduser("~/stock_bot/data/stage1_report.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(res_json, f, ensure_ascii=False, indent=2)
            return res_json
        else:
            return {"status": "ERROR", "message": f"API 오류 ({r.status_code}): {r.text}"}
    except Exception as e:
        print("DEBUG Raw Response Text:")
        print(repr(text) if 'text' in locals() else "text not defined")
        return {"status": "ERROR", "message": str(e)}

if __name__ == "__main__":
    res = run_stage1_analysis("005930", "삼성전자")
    print("\n" + "="*48)
    print("        📊 [1단계 AI 분석 보고서 결과]")
    print("="*48)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print("="*48)
