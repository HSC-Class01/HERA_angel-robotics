# 엔젤로보틱스 DART 재무 분석

[![🔗 대시보드 바로가기](https://img.shields.io/badge/🔗-대시보드%20바로가기-1769aa?style=for-the-badge)](https://HSC-Class01.github.io/HERA_angel-robotics/)

- 저장소: https://github.com/HSC-Class01/HERA_angel-robotics
- 대시보드: https://HSC-Class01.github.io/HERA_angel-robotics/
- API: https://opendart.fss.or.kr/

## 최초 설정
1. OpenDART에서 인증키 발급
2. GitHub 저장소 → Settings → Secrets and variables → Actions → New repository secret
3. 이름 `DART_API_KEY`, 값은 40자리 인증키로 저장합니다. 키를 코드에 직접 입력하지 마세요.
4. Settings → Pages에서 GitHub Actions 배포를 선택합니다.
5. Actions 탭에서 `DART financial update`를 수동 실행합니다.
6. 저장소 About → Website에 `https://HSC-Class01.github.io/HERA_angel-robotics/`를 입력합니다.

매월 1일 UTC 00:15(한국시간 09:15)에 자동 실행됩니다. 공시 목록은 2010년부터 조회하지만 OpenDART 전체 재무제표 API는 2015년 이후 제공되므로 재무수치의 시작점은 2015년입니다. 분기·반기 손익은 누적값일 수 있습니다. Peer firms는 사업영역 인접 후보이며 직접 비교 전 최신 상장·공시 범위를 확인하세요.

로컬 실행: `pip install -r requirements.txt`; PowerShell에서 `$env:DART_API_KEY="키"` 설정 후 `python src/update_data.py`.
