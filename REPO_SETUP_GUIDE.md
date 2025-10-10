# 🛠��� pyh-ai 리포지토리 생성 및 초기 설정 가이드

이 문서는 `pyh-ai` GitHub 리포지토리를 처음 생성할 때 적용해야 할 설정 항목과 그 이유를 안내합니다.  
프로젝트는 **Python 기반의 인간 중심 AI 도구**를 개발하는 오픈소스 프로젝트입니다.

---

## 1. General (일반 정보)

| 항목 | 설정값 | 비고 |
|------|--------|------|
| **Owner** | `your-github-username` | 본인의 GitHub 사용자명 또는 소속 조직 |
| **Repository name** | `pyh-ai` | 짧고 기억하기 쉬우며, 프로젝트 목적 반영 |
| **Description** | `A Python toolkit for human-centered AI development.` | 최대 350자 이내의 간략한 설명 |

> ✅ **Tip**: 리포지토리 이름은 변경이 어렵기 때문에 신중히 선택하세요.

---

## 2. Configuration (초기 설정)

다음 옵션을 **반드시 활성화**하여 표준화된 오픈소스 프로젝트 구조를 만드세요.

| 설정 항목 | 권장값 | 설명 |
|----------|--------|------|
| **Visibility** | `Public` | 오픈소스 프로젝트이므로 공개 설정 |
| **Add README** | ✔��� 체크 | 프로젝트 개요, 설치법, 사용법 문서화 |
| **Add .gitignore** | `Python` 선택 | Python 관련 임시/환경 파일 자동 무시 |
| **Add license** | `MIT License` 선택 | 자유로운 사용·수정·배포 허용 (저작권 표시 필수) |
| **Start with a template** | 미사용 | 필요 시 수동으로 구성 (초기에는 비활성화 권장) |

---

## 3. 생성 후 체크리스트

- [ ] `README.md` 파일이 자동 생성되었는지 확인  
- [ ] `.gitignore` 파일에 Python 규칙이 포함되었는지 확인  
- [ ] `LICENSE` 파일이 MIT 라이선스로 생성되었는지 확인  
- [ ] 기본 브랜치 이름이 `main`인지 확인 (필요 시 설정 변경)  
- [ ] Issues, Pull Requests, Wiki 등의 기능이 활성화되었는지 확인

---

## 4. 참고 링크

- [GitHub 리포지토리 생성 가이드](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)
- [Python용 .gitignore 예시](https://github.com/github/gitignore/blob/main/Python.gitignore)
- [MIT 라이선스 설명](https://choosealicense.com/licenses/mit/)

---

> 📌 이 문서는 리포지토리 생성 시의 **초기 설정 기준**을 제공합니다.  
> 이후 개발 과정에서는 `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` 등을 추가하여 협업 체계를 강화하세요.
