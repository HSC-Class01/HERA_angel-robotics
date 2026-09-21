# Angel Robotics (엔젤로보틱스) — OpenDART Financial Dashboard

엔젤로보틱스(종목코드 455900)의 재무 데이터를 OpenDART API에서 수집하고,
재무비율을 계산한 뒤 GitHub Pages 대시보드로 표시하는 프로젝트입니다.

## 데이터 흐름
OpenDART API → raw JSON → 정규화 CSV/JSON → 재무비율 계산 → GitHub Pages

## 실행
```bash
pip install -r requirements.txt
```

Windows PowerShell:
```powershell
$env:DART_API_KEY="발급받은_API_KEY"
```

macOS/Linux:
```bash
export DART_API_KEY="발급받은_API_KEY"
```

수집:
```bash
python -m src.pipeline --start-year 2023 --end-year 2025 --fs-div OFS
```

연결재무제표:
```bash
python -m src.pipeline --start-year 2023 --end-year 2025 --fs-div CFS
```

## GitHub Secret
Repository → Settings → Secrets and variables → Actions → New repository secret

- Name: `DART_API_KEY`
- Value: OpenDART 40자리 인증키

API 키는 코드/저장소에 직접 넣지 않습니다.

## 생성 데이터
- `data/raw/` : OpenDART 원본 JSON
- `data/processed/financial_data.csv`
- `data/processed/financial_data.json`
- `data/processed/financial_ratios.csv`
- `data/processed/financial_ratios.json`
- `data/processed/company.json`

## 대시보드
`dashboard/`는 정적 GitHub Pages 사이트입니다.

`.github/workflows/update-dart.yml`가 OpenDART 데이터를 갱신하고,
`.github/workflows/deploy-pages.yml`가 Pages에 배포합니다.

재무비율은 첨부된 「재무제표 및 재무비율 실무 가이드」의 흐름
(매출 성장 → 마진 → 현금흐름 → 재무안정성 → 자본효율성)을 반영합니다.

원천 계정이 명확하지 않은 지표는 임의 추정하지 않고 N/A로 둡니다.
