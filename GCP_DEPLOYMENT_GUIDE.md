# GCP VM 배포 및 24시간 구동 상세 가이드

본 문서는 주식 자동매매 시스템을 Google Cloud Platform (GCP)의 Compute Engine VM 인스턴스에 배포하고 24시간 안정적으로 구동하기 위한 상세 가이드입니다.

---

## 1. 전제 조건 및 준비 사항

1.  **GCP VM 인스턴스:** Ubuntu 20.04 또는 22.04 기반의 VM 인스턴스가 생성되어 있어야 합니다.
2.  **GCP SDK:** 로컬 PC에 `gcloud` 명령줄 도구가 설치되어 있어야 합니다.
3.  **산출물 파일:** 자동매매 시스템의 모든 파일(`*.py`, `*.md`, `*.json` 등)이 로컬 PC에 다운로드되어 있어야 합니다.

---

## 2. 파일 전송 및 환경 설정

### 2-1. VM 접속 및 파일 전송

1.  **SSH 접속:**
    ```bash
    # GCP Console에서 VM 인스턴스 이름과 Zone을 확인합니다.
    gcloud compute ssh [VM_NAME] --zone=[YOUR_VM_ZONE]
    ```

2.  **파일 전송 (로컬 PC에서 VM으로):**
    *   로컬 PC의 파일들이 있는 디렉토리에서 다음 명령어를 실행합니다.
    ```bash
    # 현재 디렉토리의 모든 파일을 VM의 홈 디렉토리로 전송
    gcloud compute scp * [VM_NAME]:~/ --zone=[YOUR_VM_ZONE]
    ```

### 2-2. 필수 소프트웨어 설치

VM에 접속한 후, 필요한 환경을 구축합니다.

```bash
# 1. 시스템 업데이트
sudo apt update
sudo apt upgrade -y

# 2. Python 환경 설정
sudo apt install python3 python3-pip -y

# 3. Python 라이브러리 설치 (Flask, Pandas, Gunicorn 등)
pip3 install requests beautifulsoup4 pandas konlpy flask gunicorn

# 4. Node.js 및 n8n 설치 (n8n은 Node.js 기반)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g n8n
```

---

## 3. Flask API 서버 구동 (Gunicorn + Systemd)

개발용 서버 대신, 안정적인 프로덕션 서버인 **Gunicorn**과 시스템 서비스 관리자인 **Systemd**를 사용하여 서버를 구동합니다.

### 3-1. Systemd 서비스 파일 생성

1.  서비스 파일 생성:
    ```bash
    sudo nano /etc/systemd/system/stock_api.service
    ```

2.  다음 내용을 입력합니다. (`User`와 `WorkingDirectory`는 VM 환경에 맞게 수정)
    ```ini
    [Unit]
    Description=Gunicorn instance to serve Stock API
    After=network.target

    [Service]
    User=ubuntu  # VM의 사용자 이름으로 변경 (예: ubuntu)
    Group=www-data
    WorkingDirectory=/home/ubuntu
    ExecStart=/usr/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app

    [Install]
    WantedBy=multi-user.target
    ```

### 3-2. 서비스 활성화 및 시작

```bash
# 1. Systemd 설정 리로드
sudo systemctl daemon-reload

# 2. 서비스 시작
sudo systemctl start stock_api

# 3. 재부팅 시 자동 시작 설정
sudo systemctl enable stock_api

# 4. 상태 확인 (Active: active (running) 이면 성공)
sudo systemctl status stock_api
```

---

## 4. GCP 방화벽 설정

외부에서 Flask API 서버(5000번 포트)와 n8n(5678번 포트)에 접근할 수 있도록 방화벽 규칙을 설정해야 합니다.

1.  **GCP Console** → **VPC 네트워크** → **방화벽**으로 이동합니다.
2.  **"방화벽 규칙 만들기"**를 클릭합니다.
3.  **규칙 1: Flask API (5000번 포트)**
    *   **이름:** `allow-5000-for-stock-api`
    *   **대상:** `네트워크의 모든 인스턴스`
    *   **소스 IP 범위:** `0.0.0.0/0` (모든 IP 허용)
    *   **프로토콜 및 포트:** `지정된 프로토콜 및 포트` → `tcp:5000`
4.  **규칙 2: n8n Web UI (5678번 포트)**
    *   **이름:** `allow-5678-for-n8n-ui`
    *   **대상:** `네트워크의 모든 인스턴스`
    *   **소스 IP 범위:** `0.0.0.0/0`
    *   **프로토콜 및 포트:** `지정된 프로토콜 및 포트` → `tcp:5678`

---

## 5. n8n 워크플로우 구동 및 설정

### 5-1. n8n Systemd 서비스 구동

n8n도 24시간 구동되어야 하므로, Systemd를 사용하여 구동합니다.

1.  **n8n Systemd 서비스 파일 생성:**
    ```bash
    sudo nano /etc/systemd/system/n8n.service
    ```

2.  다음 내용을 입력합니다.
    ```ini
    [Unit]
    Description=n8n Workflow Automation
    After=network.target

    [Service]
    Type=simple
    User=ubuntu # VM의 사용자 이름으로 변경
    WorkingDirectory=/home/ubuntu
    ExecStart=/usr/local/bin/n8n start
    Restart=always
    RestartSec=10

    [Install]
    WantedBy=multi-user.target
    ```

3.  **서비스 활성화 및 시작:**
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start n8n
    sudo systemctl enable n8n
    ```

### 5-2. n8n 워크플로우 수정

1.  브라우저를 통해 `http://[VM_EXTERNAL_IP]:5678`로 접속합니다.
2.  **API URL 변경:**
    *   **"종목 선정 API 호출"** 노드와 **"매매 주문 실행"** 노드의 URL을 **GCP VM의 외부 IP 주소**로 변경합니다.
        ```
        # 변경 전 (임시 URL)
        https://5000-iy02ypbvf4a067ni5wwoi-c28ca08f.manus-asia.computer/api/select_stocks
        
        # 변경 후 (GCP VM 외부 IP)
        http://[VM_EXTERNAL_IP]:5000/api/select_stocks
        ```
3.  **Google Sheets 연동:**
    *   Google Sheets 노드의 인증 정보를 설정하고, 스프레드시트 ID를 사용자님의 파일 ID로 업데이트합니다.

---

## 6. 최종 점검

1.  **Flask API 서버 테스트:**
    ```bash
    curl http://localhost:5000/api/select_stocks
    # 또는 로컬 PC에서: http://[VM_EXTERNAL_IP]:5000/api/select_stocks
    ```
2.  **n8n 스케줄 확인:**
    *   n8n UI에서 Cron 트리거가 활성화되어 있는지, 시간이 오전 9시로 설정되어 있는지 확인합니다.
3.  **시스템 활성화:**
    *   n8n 워크플로우를 **활성화(Active)** 상태로 전환합니다.

---

