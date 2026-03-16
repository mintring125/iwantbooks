# 학생 구입 희망도서 선택 시스템 - 구현 가이드

## 프로젝트 개요

황지중앙초등학교 학생들이 **웹 페이지에서 시중 서적을 검색**하고 표지·내용을 확인한 뒤 **3권을 선택**하면 엑셀 파일에 **자동 기록**되는 웹 시스템.
**학교 도서관 소장 도서와의 복본(중복) 여부도 자동 확인**하여 이미 있는 책은 선택하지 않도록 안내한다.

---

## 기술 스택

- **백엔드**: Python Flask
- **프론트엔드**: HTML + Vanilla CSS + Vanilla JS (프레임워크 없음)
- **도서 검색**: 알라딘 Open API (`http://www.aladin.co.kr/ttb/api/ItemSearch.aspx`)
- **복본 확인**: 선생님이 업로드한 소장 도서 목록 (엑셀/CSV) 기반 자동 매칭
- **엑셀 저장**: openpyxl
- **제출 기록**: JSON 파일 (`submissions.json`)
- **소장 도서 목록**: JSON 파일 (`library_catalog.json`)

### 이미 설치된 패키지
- Python 3.14, Node.js v22
- openpyxl 3.1.5, xlsxwriter 3.2.9, flask, requests

---

## 프로젝트 구조

```
c:\Users\김형석일반대초등수학교육\Desktop\구입희망\
├── app.py                          ← Flask 서버 (이미 생성됨, 수정 필요)
├── templates/
│   └── index.html                  ← 메인 페이지 (신규 생성)
├── static/
│   └── style.css                   ← 스타일시트 (신규 생성)
├── library_catalog.json            ← 소장 도서 목록 (관리자 업로드 시 자동 생성)
├── submissions.json                ← 자동 생성됨 (제출 기록)
├── {학년}학년 {반}반 희망도서.xlsx    ← 자동 생성됨 (학년/반별)
└── 2026학년도 1학기 학생 및 학부모, 교직원 구입 희망도서 (   학년   반).xlsx  ← 원본 양식
```

---

## 현재 `app.py` 상태 (이미 구현된 기능)

Claude Code가 이미 `app.py`를 구현했습니다. 현재 포함된 기능:

| 엔드포인트 | 메서드 | 기능 | 상태 |
|---|---|---|---|
| `/` | GET | 메인 HTML 페이지 렌더링 | ✅ 구현됨 |
| `/api/search?q=검색어` | GET | 알라딘 API 중계 → 도서 검색 결과 JSON | ✅ 구현됨 |
| `/api/submit` | POST | 학생 정보 + 선택 도서 3권 → 엑셀 저장 | ✅ 구현됨 |
| `/api/admin/login` | POST | 관리자 로그인 (비밀번호: `2026`) | ✅ 구현됨 |
| `/api/admin/logout` | POST | 관리자 로그아웃 | ✅ 구현됨 |
| `/api/admin/submissions` | GET | 제출 현황 조회 | ✅ 구현됨 |
| `/api/admin/export` | GET | 신청 결과 엑셀 다운로드 | ✅ 구현됨 |

현재 `app.py`의 설정:
- 알라딘 API 키: `ttbmintkaori0528001` (이미 설정됨)
- 관리자 비밀번호: `2026`
- 학년: 1~6학년, 1~2학년은 1반, 3~6학년은 1~2반
- 학생 식별: 학년 + 반 + 번호 (1~30번)

---

## 추가 구현이 필요한 기능

### ★ 복본(중복) 자동 확인 기능 (핵심 신규 기능)

학교 도서관에 이미 소장된 책을 학생이 선택하지 않도록, 검색 결과에 **"이미 도서관에 있어요!"** 경고를 자동으로 표시한다.

#### 동작 방식

```
1. 선생님이 DLS(독서로)에서 소장 도서 목록 엑셀 다운로드
2. 관리자 페이지에서 해당 엑셀 파일 업로드
3. 시스템이 도서명/ISBN을 library_catalog.json에 저장
4. 학생이 도서 검색 시, 검색 결과에 복본 여부 자동 표시
5. 복본 도서는 선택 불가 또는 경고 표시
```

#### `app.py`에 추가할 엔드포인트

| 엔드포인트 | 메서드 | 기능 |
|---|---|---|
| `POST /api/admin/upload-catalog` | POST | 소장 도서 목록 엑셀/CSV 업로드 → `library_catalog.json` 저장 |
| `GET /api/admin/catalog` | GET | 현재 등록된 소장 도서 목록 조회 |
| `DELETE /api/admin/catalog` | DELETE | 소장 도서 목록 초기화 |

#### `app.py`에 추가할 함수

```python
import re
import unicodedata

CATALOG_FILE = os.path.join(EXCEL_DIR, "library_catalog.json")

def normalize_title(title):
    """도서명 정규화: 공백/특수문자 제거, 소문자 변환"""
    if not title:
        return ""
    title = unicodedata.normalize("NFC", title)
    title = re.sub(r'[^\w가-힣a-zA-Z0-9]', '', title)
    return title.lower().strip()

def load_catalog():
    """소장 도서 목록 로드"""
    if not os.path.exists(CATALOG_FILE):
        return []
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_catalog(catalog):
    """소장 도서 목록 저장"""
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

def check_duplicate(book_title, book_isbn=""):
    """복본 확인: 도서명 또는 ISBN으로 소장 여부 확인"""
    catalog = load_catalog()
    if not catalog:
        return False

    # ISBN 매칭 (가장 정확)
    if book_isbn:
        clean_isbn = re.sub(r'[^0-9]', '', book_isbn)
        for item in catalog:
            if item.get("isbn") and re.sub(r'[^0-9]', '', item["isbn"]) == clean_isbn:
                return True

    # 도서명 매칭 (정규화 후 포함 여부)
    normalized_query = normalize_title(book_title)
    if not normalized_query:
        return False

    for item in catalog:
        normalized_catalog = normalize_title(item.get("title", ""))
        if normalized_catalog and (
            normalized_query == normalized_catalog or
            normalized_query in normalized_catalog or
            normalized_catalog in normalized_query
        ):
            return True

    return False
```

#### 검색 API 수정 (`/api/search`)

기존 검색 결과에 `isDuplicate` 필드를 추가:

```python
@app.route("/api/search")
def search_books():
    # ... 기존 알라딘 API 호출 코드 ...

    books = []
    for item in data.get("item", []):
        title = item.get("title", "")
        isbn = item.get("isbn13", item.get("isbn", ""))

        books.append({
            "title": title,
            "author": item.get("author", ""),
            "publisher": item.get("publisher", ""),
            "price": item.get("priceStandard", 0),
            "salePrice": item.get("priceSales", 0),
            "cover": item.get("cover", ""),
            "description": item.get("description", ""),
            "isbn": isbn,
            "link": item.get("link", ""),
            "categoryName": item.get("categoryName", ""),
            "pubDate": item.get("pubDate", ""),
            "isDuplicate": check_duplicate(title, isbn),  # ← 복본 여부 추가
        })
    return jsonify({"books": books})
```

#### 소장 도서 업로드 API

```python
@app.route("/api/admin/upload-catalog", methods=["POST"])
def upload_catalog():
    """소장 도서 목록 엑셀/CSV 업로드"""
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "파일을 선택해주세요."})

    filename = file.filename.lower()
    catalog = []

    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            # 엑셀 파일 파싱
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active

            # 헤더 행에서 도서명, ISBN 열 자동 감지
            header_row = 1
            title_col = None
            isbn_col = None
            author_col = None
            publisher_col = None

            for col in range(1, ws.max_column + 1):
                val = str(ws.cell(row=header_row, column=col).value or "").strip()
                if "도서명" in val or "서명" in val or "제목" in val or "자료명" in val:
                    title_col = col
                elif "ISBN" in val.upper() or "isbn" in val:
                    isbn_col = col
                elif "저자" in val or "지은이" in val or "작가" in val:
                    author_col = col
                elif "출판사" in val or "발행처" in val:
                    publisher_col = col

            if title_col is None:
                # 헤더를 못 찾으면 2번째 열을 도서명으로 가정
                title_col = 2

            for row in range(header_row + 1, ws.max_row + 1):
                title = ws.cell(row=row, column=title_col).value
                if not title or str(title).strip() == "":
                    continue

                entry = {"title": str(title).strip()}
                if isbn_col:
                    isbn_val = ws.cell(row=row, column=isbn_col).value
                    if isbn_val:
                        entry["isbn"] = str(isbn_val).strip()
                if author_col:
                    author_val = ws.cell(row=row, column=author_col).value
                    if author_val:
                        entry["author"] = str(author_val).strip()
                if publisher_col:
                    pub_val = ws.cell(row=row, column=publisher_col).value
                    if pub_val:
                        entry["publisher"] = str(pub_val).strip()

                catalog.append(entry)

        elif filename.endswith(".csv"):
            import csv
            from io import TextIOWrapper
            reader = csv.DictReader(TextIOWrapper(file, encoding="utf-8-sig"))
            for row in reader:
                title = row.get("도서명") or row.get("서명") or row.get("제목") or ""
                if title.strip():
                    entry = {"title": title.strip()}
                    for key in ["ISBN", "isbn", "isbn13"]:
                        if row.get(key):
                            entry["isbn"] = row[key].strip()
                    catalog.append(entry)
        else:
            return jsonify({"success": False, "error": "xlsx 또는 csv 파일만 업로드 가능합니다."})

        save_catalog(catalog)
        return jsonify({
            "success": True,
            "message": f"소장 도서 {len(catalog)}권이 등록되었습니다.",
            "count": len(catalog)
        })

    except Exception as e:
        return jsonify({"success": False, "error": f"파일 처리 중 오류: {str(e)}"})
```

---

### 프론트엔드 (`templates/index.html`) — 신규 생성 필요

#### 레이아웃

```
┌──────────────────────────────────────────────────┐
│  📚 2026학년도 구입 희망도서 선택                     │
├──────────────────────────────────────────────────┤
│  학년 [드롭다운]  반 [드롭다운]  번호 [드롭다운]       │
├──────────────────────────────────────────────────┤
│  🔍 [도서 검색창                        ] [검색]    │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │ 표지     │  │ 표지     │  │ 표지     │          │
│  │ 이미지   │  │ 이미지   │  │ 이미지   │          │
│  ├─────────┤  ├─────────┤  ├─────────┤          │
│  │ 제목     │  │ 제목     │  │ ⚠️ 복본! │  ← 복본 │
│  │ 저자     │  │ 저자     │  │ 도서관에 │  경고   │
│  │ 출판사   │  │ 출판사   │  │ 있어요!  │  표시   │
│  │ 가격     │  │ 가격     │  │ [선택불가]│         │
│  │ [선택]   │  │ [선택]   │  │         │         │
│  └─────────┘  └─────────┘  └─────────┘          │
│                                                  │
├──────────────────────────────────────────────────┤
│  📖 선택한 도서 (2/3)                              │
│  ┌──────────────┬──────────────┬──────────────┐  │
│  │ 1. 책 제목    │ 2. 책 제목    │ 3. (미선택)   │  │
│  │    [취소 ✕]  │    [취소 ✕]  │              │  │
│  └──────────────┴──────────────┴──────────────┘  │
│                                                  │
│              [ ✅ 제출하기 ]                       │
├──────────────────────────────────────────────────┤
│  ⚙️ 관리자 (하단 작은 텍스트 링크)                   │
└──────────────────────────────────────────────────┘
```

#### 관리자 페이지 (같은 HTML 내 모달 또는 별도 섹션)

```
┌──────────────────────────────────────────────────┐
│  ⚙️ 관리자 페이지                                  │
├──────────────────────────────────────────────────┤
│                                                  │
│  📚 소장 도서 목록 관리                             │
│  ┌────────────────────────────────────────────┐  │
│  │ 현재 등록된 소장 도서: 1,234권               │  │
│  │                                            │  │
│  │ [📁 엑셀/CSV 파일 업로드]  [🗑️ 목록 초기화]   │  │
│  │                                            │  │
│  │ 안내: DLS(독서로)에서 소장 도서 목록을         │  │
│  │ 엑셀로 다운로드한 후 여기에 업로드하세요.      │  │
│  │ 도서명 열이 포함된 엑셀이면 자동 인식됩니다.   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  📋 제출 현황                                     │
│  학년 [드롭다운]  반 [드롭다운]  [조회] [엑셀 다운로드] │
│  ┌────────────────────────────────────────────┐  │
│  │ 3학년 1반 5번 — 어린왕자, 해리포터, ...      │  │
│  │ 3학년 1반 12번 — 홍길동전, 심청전, ...       │  │
│  │ ...                                        │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

#### 주요 기능 상세

1. **학생 정보 입력**
   - 학년: 1~6 드롭다운
   - 반: 학년에 따라 동적 변경 (1~2학년: 1반만, 3~6학년: 1~2반)
   - 번호: 1~30 드롭다운
   - 세 항목 모두 선택해야 검색 가능

2. **도서 검색**
   - 검색창에 입력 후 엔터 또는 검색 버튼 클릭
   - `GET /api/search?q=검색어` 호출
   - 검색 중 로딩 스피너 표시
   - 결과를 카드 그리드로 표시 (반응형: 데스크탑 4~5열, 태블릿 3열, 모바일 2열)

3. **도서 카드 정보 표시**
   - 표지 이미지 (API의 `cover` 필드)
   - 제목 (`title`)
   - 저자 (`author`)
   - 출판사 (`publisher`)
   - 정가 (`price`, 숫자 천단위 콤마 포맷)
   - 카테고리 (`categoryName`)
   - 간단한 설명 (`description`, 2줄 제한)
   - **복본 여부** (`isDuplicate` === true 이면 경고 배지 표시)
   - "선택" 버튼 (복본인 경우 비활성화 또는 경고 후 선택 가능)

4. **복본 도서 표시 (신규)**
   - `isDuplicate: true`인 카드에는:
     - 카드 상단에 빨간색 배지: `"⚠️ 도서관 소장 도서"`
     - 카드 배경: 약간 붉은 틴트
     - 선택 버튼 대신: `"이미 도서관에 있어요"` 텍스트
     - 또는 경고 확인 후 선택 허용 (선생님 판단에 따라)

5. **도서 선택 (최대 3권)**
   - 선택 버튼 클릭 시 하단 선택 바구니에 추가
   - 이미 선택된 책은 카드에 체크마크 표시, 버튼 비활성화
   - 3권 초과 선택 시 알림: "최대 3권까지 선택할 수 있습니다"
   - 선택 바구니에서 ✕ 클릭 시 선택 취소

6. **제출**
   - 3권 모두 선택 시 제출 버튼 활성화 (그 전에는 비활성화)
   - `POST /api/submit` 호출 (JSON body)
   - 요청 body 형식:
     ```json
     {
       "grade": "3",
       "classNum": "2",
       "studentNumber": "5",
       "books": [
         {
           "title": "책 제목",
           "author": "저자",
           "publisher": "출판사",
           "price": 15000,
           "salePrice": 13500,
           "isbn": "9788901234567"
         }
       ]
     }
     ```
   - 성공 시: 성공 모달 표시 → 폼 초기화
   - 실패 시: 에러 메시지 모달 표시

7. **도서 상세 모달** (카드 클릭 시)
   - 큰 표지 이미지
   - 제목, 저자, 출판사, 가격
   - 전체 설명
   - 카테고리, 출간일
   - **복본 여부 표시**
   - "선택하기" / "닫기" 버튼

8. **관리자 기능** (하단 "관리자" 링크 클릭 → 비밀번호 입력`)
   - 소장 도서 목록 업로드 (엑셀/CSV)
   - 현재 등록된 소장 도서 수 표시
   - 소장 목록 초기화
   - 학생 제출 현황 조회 (학년/반 필터)
   - 제출 결과 엑셀 다운로드

---

### 스타일시트 (`static/style.css`) — 신규 생성 필요

#### 디자인 요구사항

- **전체 톤**: 다크 네이비 + 따뜻한 오렌지/골드 악센트
  - 배경: `#0f0f23` → `#1a1a3e` 그라데이션
  - Primary: `#ff9f43` (오렌지 골드)
  - 카드 배경: `rgba(255,255,255,0.08)` (글래스모피즘)
  - 텍스트: `#e0e0ff` (밝은 라벤더)
  - **복본 경고**: `#ff4757` (빨간색), 카드 배경 `rgba(255,71,87,0.1)`

- **폰트**: Google Fonts `Noto Sans KR` 사용
  ```html
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
  ```

- **카드 디자인**:
  - 둥근 모서리 (`border-radius: 16px`)
  - 그림자 (`box-shadow`)
  - 호버 시 살짝 위로 이동 (`transform: translateY(-4px)`)
  - 선택된 카드: 골드 테두리 + 체크 배지
  - **복본 카드: 빨간 테두리 + 경고 배지**

- **선택 바구니**: 화면 하단 고정 (`position: sticky; bottom: 0`)
  - 글래스모피즘 배경 (`backdrop-filter: blur(20px)`)
  - 선택된 도서 미니 카드 표시

- **애니메이션**:
  - 카드 등장: `fadeInUp` (순차적으로 등장)
  - 선택 시: `pulse` 효과
  - 로딩: 책 아이콘 회전 스피너
  - 모달: `fadeIn` + `slideUp`

- **반응형 디자인**:
  - 모바일 (~480px): 카드 1열
  - 태블릿 (~768px): 카드 2~3열
  - 데스크탑: 카드 4~5열

---

## 사용 흐름

### 선생님 (최초 1회)
```
1. python app.py 로 서버 실행
2. 브라우저에서 http://localhost:5000 접속
3. 하단 "관리자" 클릭 → 비밀번호 "2026" 입력
4. 소장 도서 목록 관리 → DLS에서 다운로드한 엑셀 파일 업로드
5. "소장 도서 1,234권이 등록되었습니다" 확인
```

### 학생
```
1. 브라우저에서 http://localhost:5000 접속
2. 학년/반/번호 선택
3. 도서 검색 (예: "어린왕자", "해리포터")
4. 표지와 내용 확인
   - ⚠️ "도서관 소장 도서" 표시된 책은 피해서 선택
5. 3권 선택
6. 제출
7. 엑셀 파일 자동 생성/업데이트
```

---

## 실행 방법

```bash
cd "c:\Users\김형석일반대초등수학교육\Desktop\구입희망"
python app.py
```

브라우저에서 `http://localhost:5000` 접속

---

## 검증 체크리스트

- [ ] 서버가 정상 실행되는지 확인
- [ ] 도서 검색이 동작하는지 확인 (알라딘 API)
- [ ] **관리자 로그인이 동작하는지 확인** (비밀번호: 2026)
- [ ] **소장 도서 목록 엑셀 업로드가 동작하는지 확인**
- [ ] **검색 결과에서 복본 도서에 경고가 표시되는지 확인**
- [ ] **복본 도서 선택 시 경고/차단이 동작하는지 확인**
- [ ] 도서 3권 선택이 정상 동작하는지 확인
- [ ] 제출 시 엑셀 파일이 올바르게 생성되는지 확인
- [ ] 중복 제출 방지가 동작하는지 확인
- [ ] 엑셀 파일의 컬럼(번호, 학생, 도서명, 출판사, 지은이, 수량, 정가, 할인가)이 올바른지 확인
- [ ] 반응형 디자인이 태블릿/모바일에서 정상 표시되는지 확인

---

## DLS 소장 도서 목록 다운로드 방법 (参考)

```
독서로 DLS 로그인 (사서교사/담당교사 계정)
→ https://reading.keris.or.kr
→ 도서관리 / 장서관리
→ 장서현황 / 소장자료 조회
→ 전체 조회 후 "엑셀 다운로드" 버튼 클릭
→ 다운로드된 파일을 관리자 페이지에서 업로드
```

> DLS 화면 구성은 버전에 따라 다를 수 있습니다.
> 업로드하는 엑셀 파일에 "도서명" 또는 "서명" 또는 "제목" 열이 있으면 자동 인식됩니다.

---

## 참고 사항

- `app.py`는 이미 생성되어 있습니다. **복본 확인 관련 코드를 추가 구현**해야 합니다.
- `templates/index.html`과 `static/style.css`는 **신규 생성**이 필요합니다.
- 프론트엔드에서 복본 표시 로직은 검색 결과의 `isDuplicate` 필드를 확인합니다.
