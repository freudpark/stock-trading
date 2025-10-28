# n8n 자동매매 시스템 워크플로우 설계 가이드

## 1. 워크플로우 개요

이 워크플로우는 **매일 정해진 시간(예: 오전 9:00)**에 자동으로 실행되어 다음의 작업을 수행합니다:

```
[1. 스케줄 트리거]
    ↓
[2. Python API 호출 (/api/select_stocks)]
    ↓
[3. 매수 종목 필터링 및 반복 처리]
    ↓
[4. 각 종목별 매매 주문 실행 (/api/execute_trade)]
    ↓
[5. 매매 결과를 Google Sheets에 기록]
    ↓
[6. 대시보드 자동 업데이트]
```

---

## 2. n8n 워크플로우 구성 단계별 설명

### 2-1. 노드 1: Cron 트리거 (스케줄)

**목적:** 매일 오전 9:00에 워크플로우 자동 실행

**설정:**
- **노드 타입:** Cron
- **Cron 표현식:** `0 9 * * *` (매일 오전 9:00)
- **시간대:** Asia/Seoul

**출력:** 트리거 시간 정보

---

### 2-2. 노드 2: HTTP Request (종목 선정 API 호출)

**목적:** Python Flask API 서버의 `/api/select_stocks` 엔드포인트를 호출하여 매매 대상 종목을 조회

**설정:**
- **노드 타입:** HTTP Request
- **메서드:** GET
- **URL:** `https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer/api/select_stocks`
- **인증:** 없음 (모의 환경)
- **응답 형식:** JSON

**응답 데이터 예시:**
```json
{
  "status": "success",
  "message": "종목 선정 및 매매 판단이 완료되었습니다.",
  "data": [
    {
      "name": "두산로보틱스",
      "code": "454910",
      "score": 6,
      "decision": "매수",
      "investment_amount": 3333333.33,
      "target_price": 44492,
      "reasons": "..."
    },
    ...
  ]
}
```

---

### 2-3. 노드 3: 데이터 필터링 (매수 종목만 추출)

**목적:** API 응답에서 "decision": "매수"인 종목만 필터링

**설정:**
- **노드 타입:** Set (또는 Function)
- **표현식:** 
  ```javascript
  $json.data.filter(item => item.decision === "매수")
  ```

**출력:** 매수 결정된 종목 배열

---

### 2-4. 노드 4: 반복 처리 (Loop)

**목적:** 필터링된 각 종목에 대해 매매 주문을 반복 실행

**설정:**
- **노드 타입:** Loop Over Items
- **입력:** 노드 3의 출력 (매수 종목 배열)

**반복 항목:** 각 종목의 정보 (name, code, investment_amount 등)

---

### 2-5. 노드 5: HTTP Request (매매 주문 실행)

**목적:** 각 종목별로 매매 주문을 실행

**설정:**
- **노드 타입:** HTTP Request
- **메서드:** POST
- **URL:** `https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer/api/execute_trade`
- **본문 (Body):**
  ```json
  {
    "code": "{{ $item.code }}",
    "amount": {{ $item.investment_amount }}
  }
  ```
- **헤더:** Content-Type: application/json

**응답 데이터 예시:**
```json
{
  "status": "success",
  "message": "[454910] 3,333,333원 매수 주문이 모의 환경에서 접수되었습니다.",
  "details": {
    "stock_code": "454910",
    "order_amount": 3333333.33
  }
}
```

---

### 2-6. 노드 6: Google Sheets 업데이트 (매매 로그 기록)

**목적:** 각 매매 주문 결과를 Google Sheets의 "매매 로그" 시트에 기록

**설정:**
- **노드 타입:** Google Sheets
- **작업:** Append Row
- **스프레드시트:** 사용자님의 Google Sheets 파일 선택
- **시트:** "매매 로그"
- **행 데이터:**
  ```
  {
    "날짜": "{{ now.toFormat('yyyy-MM-dd HH:mm:ss') }}",
    "종목명": "{{ $item.name }}",
    "종목코드": "{{ $item.code }}",
    "점수": "{{ $item.score }}",
    "매매판단": "{{ $item.decision }}",
    "투자금액": "{{ $item.investment_amount }}",
    "목표가": "{{ $item.target_price }}",
    "상태": "주문접수"
  }
  ```

**필수 설정:**
- Google 계정 인증 필요
- 스프레드시트 공유 권한 필요

---

### 2-7. 노드 7: 조건부 분기 (에러 처리)

**목적:** 매매 주문 실행 중 에러가 발생하면 알림 전송

**설정:**
- **노드 타입:** IF
- **조건:** `{{ $json.status !== "success" }}`
- **True 분기:** 에러 알림 (Telegram, 이메일 등)
- **False 분기:** 계속 진행

---

### 2-8. 노드 8: 대시보드 업데이트 (요약 정보)

**목적:** 모든 매매가 완료된 후, Google Sheets의 "대시보드" 시트를 업데이트

**설정:**
- **노드 타입:** Google Sheets
- **작업:** Update Row
- **업데이트 항목:**
  - 마지막 실행 시간
  - 오늘 매매 건수
  - 총 투자 금액
  - 현재 보유 종목 수

---

## 3. Google Sheets 대시보드 구조

### 시트 1: "대시보드" (메인 대시보드)

| 항목 | 값 | 설명 |
| :--- | :--- | :--- |
| 마지막 실행 시간 | 2025-10-28 09:00:00 | 워크플로우 마지막 실행 시간 |
| 오늘 매매 건수 | 3 | 오늘 실행된 매매 건수 |
| 총 투자 금액 | 10,000,000 | 오늘 투자한 총 금액 |
| 현재 보유 종목 수 | 3 | 현재 보유 중인 종목 수 |
| 누적 수익률 (%) | +5.2 | 전체 누적 수익률 |
| 오늘 수익률 (%) | +2.1 | 오늘의 수익률 |

### 시트 2: "매매 로그" (거래 기록)

| 날짜 | 종목명 | 종목코드 | 점수 | 매매판단 | 투자금액 | 목표가 | 현재가 | 수익률 | 상태 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2025-10-28 09:00 | 두산로보틱스 | 454910 | 6 | 매수 | 3,333,333 | 44,492 | 43,000 | -3.4% | 주문접수 |
| 2025-10-28 09:05 | 레인보우로보틱스 | 277810 | 6 | 매수 | 3,333,333 | 33,470 | 32,500 | -2.9% | 주문접수 |
| 2025-10-28 09:10 | 삼성전자 | 005930 | 4 | 매수 | 3,333,333 | 45,917 | 44,500 | -3.1% | 주문접수 |

### 시트 3: "보유 종목" (포트폴리오)

| 종목명 | 종목코드 | 매수가 | 수량 | 현재가 | 평가금액 | 수익/손실 | 수익률 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 두산로보틱스 | 454910 | 43,000 | 77 | 43,500 | 3,349,500 | 16,167 | +0.5% |
| 레인보우로보틱스 | 277810 | 32,500 | 102 | 33,000 | 3,366,000 | 51,000 | +1.5% |
| 삼성전자 | 005930 | 44,500 | 74 | 45,000 | 3,330,000 | -3,333 | -0.1% |

### 시트 4: "수익률 추이" (일별 수익률 그래프용 데이터)

| 날짜 | 일일 수익률 (%) | 누적 수익률 (%) |
| :--- | :--- | :--- |
| 2025-10-27 | -1.2 | -1.2 |
| 2025-10-28 | +0.6 | -0.6 |
| 2025-10-29 | +2.3 | +1.7 |

---

## 4. n8n 워크플로우 JSON 구조 (참고용)

```json
{
  "name": "자동매매 시스템",
  "nodes": [
    {
      "name": "Cron 트리거",
      "type": "n8n-nodes-base.cron",
      "typeVersion": 1,
      "position": [250, 300],
      "parameters": {
        "cronExpression": "0 9 * * *"
      }
    },
    {
      "name": "종목 선정 API 호출",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [450, 300],
      "parameters": {
        "method": "GET",
        "url": "https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer/api/select_stocks"
      }
    },
    {
      "name": "매수 종목 필터링",
      "type": "n8n-nodes-base.set",
      "typeVersion": 1,
      "position": [650, 300],
      "parameters": {
        "options": {
          "values": [
            {
              "name": "filtered_stocks",
              "value": "={{ $json.data.filter(item => item.decision === '매수') }}"
            }
          ]
        }
      }
    },
    {
      "name": "반복 처리",
      "type": "n8n-nodes-base.loopOver",
      "typeVersion": 1,
      "position": [850, 300],
      "parameters": {
        "nodeToLoopOver": "매수 종목 필터링"
      }
    },
    {
      "name": "매매 주문 실행",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [1050, 300],
      "parameters": {
        "method": "POST",
        "url": "https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer/api/execute_trade",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": "={{ JSON.stringify({ code: $item.code, amount: $item.investment_amount }) }}"
      }
    },
    {
      "name": "Google Sheets 업데이트",
      "type": "n8n-nodes-base.googleSheets",
      "typeVersion": 4,
      "position": [1250, 300],
      "parameters": {
        "operation": "appendRow",
        "spreadsheetId": "YOUR_SPREADSHEET_ID",
        "sheetName": "매매 로그",
        "values": [
          "={{ now.toFormat('yyyy-MM-dd HH:mm:ss') }}",
          "={{ $item.name }}",
          "={{ $item.code }}",
          "={{ $item.score }}",
          "={{ $item.decision }}",
          "={{ $item.investment_amount }}",
          "={{ $item.target_price }}",
          "주문접수"
        ]
      }
    }
  ],
  "connections": {
    "Cron 트리거": {
      "main": [
        [
          {
            "node": "종목 선정 API 호출",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "종목 선정 API 호출": {
      "main": [
        [
          {
            "node": "매수 종목 필터링",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "매수 종목 필터링": {
      "main": [
        [
          {
            "node": "반복 처리",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "반복 처리": {
      "main": [
        [
          {
            "node": "매매 주문 실행",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "매매 주문 실행": {
      "main": [
        [
          {
            "node": "Google Sheets 업데이트",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  }
}
```

---

## 5. 사용자 설정 가이드

### 5-1. n8n 설치 및 시작

```bash
# n8n 설치
npm install -g n8n

# n8n 시작
n8n start
```

### 5-2. Google Sheets 연동 설정

1. **Google Cloud Console에서 OAuth 2.0 인증 설정**
   - Google Cloud 프로젝트 생성
   - Google Sheets API 활성화
   - OAuth 2.0 클라이언트 ID 생성

2. **n8n에서 Google Sheets 노드 설정**
   - Google Sheets 노드 추가
   - "Authenticate with Google" 버튼 클릭
   - Google 계정으로 로그인 및 권한 승인
   - 스프레드시트 선택

### 5-3. Flask API 서버 설정

- **API URL:** `https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer`
- **엔드포인트 1:** `/api/select_stocks` (GET)
- **엔드포인트 2:** `/api/execute_trade` (POST)

---

## 6. 워크플로우 실행 및 모니터링

### 6-1. 수동 실행

n8n 대시보드에서 "Execute Workflow" 버튼을 클릭하여 수동으로 워크플로우를 실행할 수 있습니다.

### 6-2. 자동 실행

Cron 트리거가 설정되어 있으므로, 매일 오전 9:00에 자동으로 워크플로우가 실행됩니다.

### 6-3. 실행 로그 확인

n8n 대시보드의 "Execution History" 탭에서 모든 실행 기록과 결과를 확인할 수 있습니다.

---

## 7. 다음 단계 (실제 거래소 연동)

현재는 **모의 환경**에서 작동하고 있습니다. 실제 거래소(한국투자증권)와 연동하려면:

1. **한국투자증권 API 인증 정보 설정**
   - App Key, Secret Key 환경변수에 저장
   - OAuth 토큰 발급 로직 구현

2. **모의투자 환경에서 테스트**
   - 한국투자증권 모의투자 계좌 개설
   - 백테스팅 수행

3. **실전 거래로 전환**
   - 실제 계좌 연동
   - 소액부터 시작하여 점진적 확대


