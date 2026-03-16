# Railway Deploy

## 1. 새 프로젝트 만들기
- Railway에서 `New Project`를 누릅니다.
- 이 폴더를 GitHub에 올린 뒤 `Deploy from GitHub repo`로 연결합니다.

## 2. Postgres 추가
- 프로젝트 안에서 `New` -> `Database` -> `PostgreSQL`을 추가합니다.
- Railway가 `DATABASE_URL`을 자동으로 제공합니다.

## 3. 환경 변수
- `SECRET_KEY`: 임의의 긴 문자열
- `ADMIN_PASSWORD`: `2026`
- `ALADIN_API_KEY`: 알라딘 TTB Key

## 4. 실행 설정
- 이 저장소에는 이미 `requirements.txt`, `Procfile`, `railway.json`이 들어 있습니다.
- 시작 명령은 `gunicorn app:app`입니다.

## 5. 동작 방식
- 로컬: `DATABASE_URL`이 없으면 `sqlite:///school_books.db`
- Railway: `DATABASE_URL`이 있으면 PostgreSQL 사용
- 테이블은 앱 시작 시 자동 생성됩니다.

## 6. 기존 데이터
- 처음 실행할 때 `submissions.json`이나 `library_catalog.json`이 있으면 DB가 비어 있을 때 한 번 가져옵니다.

## 7. 주의
- 이제 학생 제출 데이터는 JSON 파일이 아니라 DB에 저장됩니다.
- 관리자 `xlsx` 다운로드는 DB 데이터를 기준으로 즉시 생성됩니다.
