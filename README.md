# 엔젤로보틱스 DART 재무 데이터 에이전트

[![🔗 대시보드 바로가기](https://img.shields.io/badge/🔗-대시보드%20바로가기-1769aa?style=for-the-badge)](https://HSC-Class01.github.io/HERA_angel-robotics/)

**저장소:** https://github.com/HSC-Class01/HERA_angel-robotics  
**대시보드:** https://HSC-Class01.github.io/HERA_angel-robotics/  
**OpenDART:** https://opendart.fss.or.kr/

## 기능

- 엔젤로보틱스의 사업보고서, 반기보고서, 분기보고서 재무 수치 수집
- 공시 목록은 2010년부터 조회하고, 전체 재무제표 API는 제공 범위인 2015년 이후를 수집
- 주요 재무수치 및 재무비율을 CSV로 저장
- 차트와 Annual / Half-year / Quarterly 테이블을 포함한 GitHub Pages 대시보드
- 매월 1일 한국시간 09:15 자동 실행 (GitHub Actions 스케줄은 상황에 따라 지연될 수 있음)
- 국내 peer firms 후보 표를 README와 대시보드에 표시

## 꼭 알아둘 데이터 한계

1. OpenDART의 [`fnlttSinglAcntAll` 전체 재무제표 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020)는 **2015년 이후** 데이터를 제공한다고 공식 개발가이드에 명시되어 있습니다. 따라서 2010년부터 공시 목록을 조회하지만, 이 API를 통한 상세 재무 수치 수집은 2015년부터입니다. 회사 설립 전 기간이나 미제출 기간은 데이터가 없습니다.
2. 본 패키지는 API에서 제공하는 재무제표 계정 행과 접수번호를 저장합니다. 원본 DART 뷰어 문서 전체(PDF/HTML)를 별도로 다운로드하는 패키지는 아닙니다. `filings_2010_onward.csv`의 접수번호로 원문에 접근할 수 있습니다.
3. 분기보고서의 손익·현금흐름 수치는 당분기와 누적값이 함께 제공될 수 있습니다. 이 패키지는 `thstrm_amount`와 `thstrm_add_amount`를 모두 보존하고, 반기 지표 계산에 누적값을 우선 사용합니다. 계정별 공시 방식 차이는 분석 전에 확인해야 합니다. ROA/ROE/자산회전율은 가능한 경우 해당 기간의 기초·기말 평균 잔액을 사용합니다.
4. 계정명이 회사/연도에 따라 달라서 일부 비율이 결측값일 수 있습니다. 결측값은 0으로 채우지 않습니다. 반기·분기 수익성 및 활동성 비율은 기간 실적 기준이며 연환산하지 않으므로 연간 비율과 직접 비교하지 마세요. 계산 결과는 참고용이며 투자 권유가 아닙니다.
5. 「재무제표 및 재무비율 실무 가이드」의 주요 항목을 반영했습니다. 평균 자산·평균 자본 기준 ROA/ROE, CFO/순이익, 순차입금, 이자보상배율, 총자산회전율, DSO/DIO/DPO/CCC를 가능한 범위에서 계산합니다. 계정이 누락되면 결측으로 남기며 임의 추정하지 않습니다.

## GitHub 설정 순서

### 1. ZIP 업로드

ZIP을 풀고 **폴더 안의 모든 파일을 저장소 최상위에** 업로드합니다. `HERA_angel_robotics_agent` 폴더 전체를 저장소 안에 한 겹 더 넣지 마세요. `.github/workflows/` 폴더는 자동화에 꼭 필요합니다. 숨김 폴더를 업로드하기 쉬운 방법은 아래 Git 명령을 사용하는 것입니다.

```bash
git clone https://github.com/HSC-Class01/HERA_angel-robotics.git
cd HERA_angel-robotics
# 압축 해제한 ZIP 폴더의 내용 전체를 이 저장소 루트로 복사
git add .
git commit -m "Add DART financial agent and dashboard"
git push
```

Git 명령은 Windows PowerShell에서도 Git이 설치되어 있으면 사용할 수 있습니다. 파일 업로드 화면에서 `.github` 폴더가 보이지 않으면 웹 업로드 대신 이 방식을 권장합니다.

### 2. DART API Secret 등록

1. [OpenDART](https://opendart.fss.or.kr/)에서 API 인증키를 발급합니다.
2. GitHub 저장소에서 **Settings → Secrets and variables → Actions → New repository secret**을 엽니다.
3. Name은 `DART_API_KEY`, Secret은 발급받은 40자리 키로 입력하고 저장합니다.
4. API 키를 Python 파일, README 또는 커밋 이력에 직접 넣지 마세요.

### 3. GitHub Pages 설정

1. 저장소 **Settings → Pages**로 갑니다.
2. Build and deployment의 Source를 **GitHub Actions**로 선택합니다.
3. Actions 탭에서 `DART financial update`를 선택하고 **Run workflow**로 최초 수집을 실행합니다.
4. 성공하면 대시보드는 `https://HSC-Class01.github.io/HERA_angel-robotics/` 에 게시됩니다.
5. 저장소 오른쪽 **About → 톱니바퀴(Edit repository details) → Website**에 대시보드 주소를 입력합니다.
6. README 최상단에는 대시보드 바로가기 배지가 이미 포함되어 있습니다.

> 정기 스케줄은 GitHub 저장소의 기본 브랜치에서만 실행됩니다. 이 패키지에는 수집·커밋·Pages 배포를 하나의 워크플로에서 처리하도록 구성해 두어 두 배포 워크플로 간 충돌 가능성을 줄였습니다.

## 자동 업데이트

`.github/workflows/update-data.yml`의 cron은 `15 0 1 * *` 입니다. GitHub Actions는 UTC를 사용하므로 한국시간 매월 1일 오전 9시 15분에 실행됩니다. API 수집 후 데이터/대시보드를 커밋하고 GitHub Pages를 다시 배포합니다. 실행 시간은 GitHub 부하로 지연될 수 있으며, Actions 탭에서 수동 실행도 가능합니다.

## 생성 파일

- `data/raw/filings_2010_onward.csv`: 2010년 이후 정기공시 접수 목록 (사업·반기·분기 보고서 위주)
- `data/raw/financial_YYYY_CODE.json`: OpenDART API 원 응답
- `data/processed/financial_data.csv`: 계정 단위 원자료 및 누적/당기 금액
- `data/processed/financial_ratios.csv`: 주요 재무수치·재무비율, 운전자본 관련 지표
- `dashboard/index.html`: GitHub Pages가 게시하는 대시보드
- `templates/dashboard.html`: 데이터 수집 후 대시보드 생성에 사용하는 템플릿

## 주요 분석 항목

| 범주 | 항목 |
|---|---|
| 손익 | 매출액, 매출총이익(계정이 제공되는 경우), 영업이익, 당기순이익, 매출증가율 |
| 재무상태 | 유동자산, 비유동자산, 자산총계, 현금및현금성자산, 유동부채, 비유동부채, 부채총계, 자본총계, 단·장기차입금 |
| 현금흐름 | CFO/CFI/CFF, CAPEX, FCF, CFO/순이익 |
| 자금부담 | 이자부차입금, 순차입금, 차입금의존도, 이자보상배율, (연간) 순차입금/EBITDA |
| 비율·활동성 | 매출·총이익·영업이익·순이익률, EPS(공시 계정 존재 시), EBITDA(상각비 계정 검증 시), ROA/ROE(평균 잔액 사용), ROIC(유효세율/평균 투하자본 확인 시), 총자산회전율, 유동·당좌비율, DSO/DIO/DPO/CCC |

## 국내 Peer Firms 후보

아래는 제품·시장 인접도를 기준으로 한 비교 후보이며, 사업 구조와 회계 기준이 같다는 뜻은 아닙니다. 정량 비교 시 연결/별도 기준, 의료·재활/웨어러블 매출 비중, 기업 규모 및 최근 공시를 따로 확인해야 합니다.

| 기업 | 비교 이유 | 상장/공시 참고 |
|---|---|---|
| 코스모로보틱스 | 웨어러블 의료재활·보행보조·산업용 슈트 | 코스닥 상장 (2026년 9월 자료 기준, 코드 439960) |
| 위로보틱스 | 웨어러블 보행보조·근력보조 로봇 | 비상장 후보; 공개 재무자료 범위 제한 가능 |
| 큐렉소 | 의료로봇 및 보행 재활로봇 Morning Walk | 코스닥 상장사; 의료로봇 인접 비교 |
| 네오펙트 | 디지털 재활·재활 솔루션 | 상장 상태 및 최근 공시 여부 확인 필요 |
| 로보티즈 | 로봇 구동부품/서비스 로봇 | 간접 참고기업; 제품 시장이 다름 |

참고: [코스모로보틱스 기업정보(종목코드 439960)](https://comp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=439960), [코스모로보틱스](https://www.csm-rbtipo.com/), [위로보틱스](https://wirobotics.career.greetinghr.com/), [큐렉소](https://www.curexo.com/), [OpenDART](https://opendart.fss.or.kr/).
