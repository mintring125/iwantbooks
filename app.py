import csv
import io
import json
import os
import re
import unicodedata
from datetime import datetime
from io import BytesIO, TextIOWrapper

import openpyxl
import requests
from flask import Flask, jsonify, render_template, request, send_file, session
from flask_sqlalchemy import SQLAlchemy
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from sqlalchemy import UniqueConstraint


def build_database_url():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        return "sqlite:///school_books.db"
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "purchase-wishlist-2026")
app.config["SQLALCHEMY_DATABASE_URI"] = build_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
db_initialized = False

ALADIN_API_KEY = os.environ.get("ALADIN_API_KEY", "ttbmintkaori0528001")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "2026")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBMISSIONS_FILE = os.path.join(BASE_DIR, "submissions.json")
CATALOG_FILE = os.path.join(BASE_DIR, "library_catalog.json")

SCHOOL_STRUCTURE = {
    "1": {"1": 11},
    "2": {"1": 15},
    "3": {"1": 11, "2": 11},
    "4": {"1": 17, "2": 16},
    "5": {"1": 17, "2": 16},
    "6": {"1": 19, "2": 20},
}
GRADE_OPTIONS = list(SCHOOL_STRUCTURE.keys())


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    grade = db.Column(db.String(2), nullable=False)
    class_num = db.Column(db.String(2), nullable=False)
    student_number = db.Column(db.String(3), nullable=False)
    student_label = db.Column(db.String(32), nullable=False)
    books_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("grade", "class_num", "student_number", name="uq_student_slot"),
    )

    def to_dict(self):
        return {
            "grade": self.grade,
            "classNum": self.class_num,
            "studentNumber": self.student_number,
            "studentLabel": self.student_label,
            "books": json.loads(self.books_json),
            "timestamp": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class CatalogBook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    normalized_title = db.Column(db.String(500), nullable=False, index=True)
    isbn = db.Column(db.String(32), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {"title": self.title, "isbn": self.isbn or ""}


def class_options_for_grade(grade):
    return list(SCHOOL_STRUCTURE.get(str(grade), {}).keys())


def student_numbers_for_class(grade, class_num):
    max_number = SCHOOL_STRUCTURE.get(str(grade), {}).get(str(class_num), 0)
    return [str(i) for i in range(1, max_number + 1)]


def normalize_title(title):
    if not title:
        return ""
    normalized = unicodedata.normalize("NFC", str(title))
    normalized = re.sub(r"[^0-9A-Za-z가-힣]", "", normalized)
    return normalized.lower().strip()


def normalize_isbn(isbn):
    return re.sub(r"[^0-9]", "", str(isbn or ""))


def check_duplicate(book_title, book_isbn=""):
    ensure_database_ready()
    clean_isbn = normalize_isbn(book_isbn)
    if clean_isbn:
        if db.session.query(CatalogBook.id).filter(CatalogBook.isbn == clean_isbn).first():
            return True

    normalized_query = normalize_title(book_title)
    if not normalized_query:
        return False

    for item in CatalogBook.query.with_entities(CatalogBook.normalized_title).all():
        normalized_catalog = item[0]
        if normalized_catalog and (
            normalized_query == normalized_catalog
            or normalized_query in normalized_catalog
            or normalized_catalog in normalized_query
        ):
            return True
    return False


def build_border():
    return Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )


def build_admin_workbook(submissions):
    """
    첨부된 원본 양식과 동일한 엑셀 파일을 생성합니다.
    - 학년/반 조합별로 별도 시트를 생성
    - 각 시트는 원본 양식: 순 | 도서명 | 출판사 | 지은이 | 수량 | 금액(정가) | 할인금액
    - 40행 데이터 + 합계행
    """
    workbook = openpyxl.Workbook()
    # 기본 시트 제거용 (나중에 삭제)
    default_sheet = workbook.active

    thin_border = build_border()
    center_align = Alignment(horizontal="center", vertical="center")
    header_font = Font(name="맑은 고딕", bold=True, size=14)
    col_header_font = Font(name="맑은 고딕", bold=True, size=10)
    col_header_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

    # 학년/반별로 제출 데이터 그룹핑
    groups = {}
    for sub in submissions:
        key = (sub["grade"], sub["classNum"])
        if key not in groups:
            groups[key] = []
        # 학생 한 명당 도서 3권을 각각 한 행으로 펼침
        for book in sub.get("books", []):
            groups[key].append(book)

    # 제출이 없으면 빈 시트 하나 생성
    if not groups:
        groups[("", "")] = []

    created_sheets = 0
    for (grade, class_num), books in sorted(groups.items()):
        if grade and class_num:
            sheet_name = f"{grade}학년 {class_num}반"
        elif grade:
            sheet_name = f"{grade}학년"
        else:
            sheet_name = "희망도서"

        ws = workbook.create_sheet(title=sheet_name)
        created_sheets += 1

        # ── 1행: 제목 (A1:G1 병합) ──
        ws.merge_cells("A1:G1")
        title_text = f"2026년 ({grade})학년 ({class_num})반 학생, 학부모 구입 희망도서 목록"
        title_cell = ws.cell(row=1, column=1, value=title_text)
        title_cell.font = header_font
        title_cell.alignment = center_align

        # ── 2행: 컬럼 헤더 (노란색) ──
        col_headers = ["순", "도서명", "출판사", "지은이", "수량", "금액(정가)", "할인금액"]
        for col_idx, header in enumerate(col_headers, 1):
            cell = ws.cell(row=2, column=col_idx, value=header)
            cell.font = col_header_font
            cell.fill = col_header_fill
            cell.border = thin_border
            cell.alignment = center_align

        # ── 컬럼 너비 ──
        ws.column_dimensions["A"].width = 5
        ws.column_dimensions["B"].width = 35
        ws.column_dimensions["C"].width = 15
        ws.column_dimensions["D"].width = 15
        ws.column_dimensions["E"].width = 8
        ws.column_dimensions["F"].width = 12
        ws.column_dimensions["G"].width = 12

        # ── 3~42행: 40줄 데이터 영역 ──
        for row_num in range(3, 43):
            seq = row_num - 2
            # 순번
            ws.cell(row=row_num, column=1, value=seq).border = thin_border
            ws.cell(row=row_num, column=1).alignment = center_align
            # 나머지 열 빈칸 + 테두리
            for col_idx in range(2, 8):
                ws.cell(row=row_num, column=col_idx).border = thin_border

            # 실제 도서 데이터 채우기
            book_idx = seq - 1  # 0-based
            if book_idx < len(books):
                book = books[book_idx]
                price = int(book.get("price", 0) or 0)
                sale_price = int(book.get("salePrice", 0) or 0)
                if not sale_price and price:
                    sale_price = int(price * 0.9)

                ws.cell(row=row_num, column=2, value=book.get("title", ""))
                ws.cell(row=row_num, column=3, value=book.get("publisher", ""))
                ws.cell(row=row_num, column=4, value=book.get("author", ""))
                ws.cell(row=row_num, column=5, value=1)
                ws.cell(row=row_num, column=5).alignment = center_align
                ws.cell(row=row_num, column=6, value=price)
                ws.cell(row=row_num, column=6).number_format = "#,##0"
                ws.cell(row=row_num, column=7, value=sale_price)
                ws.cell(row=row_num, column=7).number_format = "#,##0"
            else:
                # 빈 행의 할인금액에 0
                ws.cell(row=row_num, column=7, value=0)
                ws.cell(row=row_num, column=7).number_format = "#,##0"

        # ── 43행: 합계 ──
        ws.cell(row=43, column=2, value="계").alignment = center_align
        ws.cell(row=43, column=2).font = col_header_font
        ws.cell(row=43, column=2).border = thin_border
        for col_idx in [1, 3, 4, 5, 6]:
            ws.cell(row=43, column=col_idx).border = thin_border
        ws.cell(row=43, column=7, value="=SUM(G3:G42)")
        ws.cell(row=43, column=7).number_format = "#,##0"
        ws.cell(row=43, column=7).border = thin_border

    # 기본 빈 시트 제거
    if created_sheets > 0 and default_sheet.title == "Sheet":
        workbook.remove(default_sheet)

    return workbook


def require_admin():
    return session.get("is_admin") is True


def query_submissions(grade="", class_num=""):
    ensure_database_ready()
    query = Submission.query.order_by(
        Submission.grade.asc(),
        Submission.class_num.asc(),
        Submission.student_number.asc(),
    )
    if grade:
        query = query.filter(Submission.grade == str(grade))
    if class_num:
        query = query.filter(Submission.class_num == str(class_num))
    return [item.to_dict() for item in query.all()]


def bootstrap_submissions_from_json():
    if Submission.query.count() > 0 or not os.path.exists(SUBMISSIONS_FILE):
        return

    try:
        with open(SUBMISSIONS_FILE, "r", encoding="utf-8") as file:
            raw_items = json.load(file)
    except Exception:
        return

    for item in raw_items:
        grade = str(item.get("grade", "")).strip()
        class_num = str(item.get("classNum", "")).strip()
        student_number = str(item.get("studentNumber", item.get("name", ""))).strip()
        books = item.get("books", [])
        if grade not in GRADE_OPTIONS:
            continue
        if class_num not in class_options_for_grade(grade):
            continue
        if student_number not in student_numbers_for_class(grade, class_num):
            continue

        created_at = datetime.utcnow()
        timestamp = str(item.get("timestamp", "")).strip()
        if timestamp:
            try:
                created_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass

        exists = (
            Submission.query.filter_by(
                grade=grade, class_num=class_num, student_number=student_number
            ).first()
            is not None
        )
        if exists:
            continue

        db.session.add(
            Submission(
                grade=grade,
                class_num=class_num,
                student_number=student_number,
                student_label=f"{grade}학년 {class_num}반 {student_number}번",
                books_json=json.dumps(books, ensure_ascii=False),
                created_at=created_at,
            )
        )
    db.session.commit()


def bootstrap_catalog_from_json():
    if CatalogBook.query.count() > 0 or not os.path.exists(CATALOG_FILE):
        return

    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as file:
            raw_items = json.load(file)
    except Exception:
        return

    for item in raw_items:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        isbn = normalize_isbn(item.get("isbn", ""))
        db.session.add(
            CatalogBook(
                title=title,
                normalized_title=normalize_title(title),
                isbn=isbn or None,
            )
        )
    db.session.commit()


def initialize_database():
    global db_initialized
    if db_initialized:
        return
    with app.app_context():
        db.create_all()
        bootstrap_submissions_from_json()
        bootstrap_catalog_from_json()
    db_initialized = True


def ensure_database_ready():
    try:
        initialize_database()
    except Exception as exc:
        app.logger.exception("Database initialization failed: %s", exc)
        raise


@app.route("/")
def index():
    ensure_database_ready()
    return render_template(
        "index.html",
        has_api_key=bool(ALADIN_API_KEY),
        grades=GRADE_OPTIONS,
        school_structure=SCHOOL_STRUCTURE,
    )


@app.route("/api/search")
def search_books():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"books": [], "error": "검색어를 입력해 주세요."})

    if not ALADIN_API_KEY:
        return jsonify({"books": [], "error": "알라딘 API 키가 설정되어 있지 않습니다."})

    try:
        response = requests.get(
            "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx",
            params={
                "ttbkey": ALADIN_API_KEY,
                "Query": query,
                "QueryType": "Keyword",
                "MaxResults": 20,
                "start": 1,
                "SearchTarget": "Book",
                "output": "js",
                "Version": "20131101",
                "Cover": "Big",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return jsonify({"books": [], "error": f"검색 중 오류가 발생했습니다: {exc}"})

    books = []
    for item in data.get("item", []):
        title = item.get("title", "")
        isbn = item.get("isbn13", item.get("isbn", ""))
        books.append(
            {
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
                "isDuplicate": check_duplicate(title, isbn),
            }
        )
    return jsonify({"books": books})


@app.route("/api/submit", methods=["POST"])
def submit_books():
    ensure_database_ready()
    data = request.get_json() or {}
    grade = str(data.get("grade", "")).strip()
    class_num = str(data.get("classNum", "")).strip()
    student_number = str(data.get("studentNumber", "")).strip()
    books = data.get("books", [])

    if grade not in GRADE_OPTIONS:
        return jsonify({"success": False, "error": "학년을 다시 선택해 주세요."})
    if class_num not in class_options_for_grade(grade):
        return jsonify({"success": False, "error": "반을 다시 선택해 주세요."})
    if student_number not in student_numbers_for_class(grade, class_num):
        return jsonify({"success": False, "error": "번호를 다시 선택해 주세요."})
    if len(books) != 3:
        return jsonify({"success": False, "error": "희망 도서 3권을 모두 선택해 주세요."})

    existing = Submission.query.filter_by(
        grade=grade, class_num=class_num, student_number=student_number
    ).first()
    if existing:
        return jsonify(
            {
                "success": False,
                "error": f"{grade}학년 {class_num}반 {student_number}번은 이미 제출했습니다.",
            }
        )

    submission = Submission(
        grade=grade,
        class_num=class_num,
        student_number=student_number,
        student_label=f"{grade}학년 {class_num}반 {student_number}번",
        books_json=json.dumps(
            [
                {
                    "title": book.get("title", ""),
                    "author": book.get("author", ""),
                    "publisher": book.get("publisher", ""),
                    "price": int(book.get("price", 0) or 0),
                    "salePrice": int(book.get("salePrice", 0) or 0),
                    "isbn": book.get("isbn", ""),
                }
                for book in books
            ],
            ensure_ascii=False,
        ),
    )
    db.session.add(submission)
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"{grade}학년 {class_num}반 {student_number}번 신청이 저장되었습니다.",
        }
    )


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json() or {}
    password = str(data.get("password", "")).strip()

    if password != ADMIN_PASSWORD:
        session["is_admin"] = False
        return jsonify({"success": False, "error": "비밀번호가 올바르지 않습니다."}), 401

    session["is_admin"] = True
    return jsonify({"success": True})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session["is_admin"] = False
    return jsonify({"success": True})


@app.route("/api/admin/submissions")
def admin_submissions():
    ensure_database_ready()
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401

    grade = request.args.get("grade", "").strip()
    class_num = request.args.get("classNum", "").strip()
    return jsonify({"submissions": query_submissions(grade=grade, class_num=class_num)})


@app.route("/api/admin/export")
def admin_export():
    ensure_database_ready()
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401

    grade = request.args.get("grade", "").strip()
    class_num = request.args.get("classNum", "").strip()
    workbook = build_admin_workbook(query_submissions(grade=grade, class_num=class_num))
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    filename_parts = ["희망도서_신청결과"]
    if grade:
        filename_parts.append(f"{grade}학년")
    if class_num:
        filename_parts.append(f"{class_num}반")

    return send_file(
        buffer,
        as_attachment=True,
        download_name="_".join(filename_parts) + ".xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/api/admin/catalog", methods=["GET"])
def get_catalog():
    ensure_database_ready()
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401
    books = CatalogBook.query.order_by(CatalogBook.title.asc()).all()
    return jsonify({"catalog": [book.to_dict() for book in books]})


@app.route("/api/admin/catalog", methods=["DELETE"])
def clear_catalog():
    ensure_database_ready()
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401
    CatalogBook.query.delete()
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/upload-catalog", methods=["POST"])
def upload_catalog():
    ensure_database_ready()
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401

    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"success": False, "error": "파일을 선택해 주세요."})

    filename = uploaded_file.filename.lower()
    catalog_rows = []

    try:
        if filename.endswith((".xlsx", ".xls")):
            workbook = openpyxl.load_workbook(uploaded_file, data_only=True)
            worksheet = workbook.active

            header_row = 1
            title_col = None
            isbn_col = None

            for col in range(1, worksheet.max_column + 1):
                value = str(worksheet.cell(row=header_row, column=col).value or "").strip()
                lowered = value.lower()
                if any(token in value for token in ["도서명", "서명", "제목", "자료명"]):
                    title_col = col
                elif "isbn" in lowered:
                    isbn_col = col

            if title_col is None:
                title_col = 1

            for row in range(header_row + 1, worksheet.max_row + 1):
                title = str(worksheet.cell(row=row, column=title_col).value or "").strip()
                if not title:
                    continue
                isbn = ""
                if isbn_col:
                    isbn = str(worksheet.cell(row=row, column=isbn_col).value or "").strip()
                catalog_rows.append({"title": title, "isbn": isbn})

        elif filename.endswith(".csv"):
            wrapper = TextIOWrapper(uploaded_file.stream, encoding="utf-8-sig")
            reader = csv.DictReader(wrapper)
            for row in reader:
                title = (
                    row.get("도서명")
                    or row.get("서명")
                    or row.get("제목")
                    or row.get("자료명")
                    or ""
                ).strip()
                if not title:
                    continue
                isbn = (row.get("ISBN") or row.get("isbn") or row.get("isbn13") or "").strip()
                catalog_rows.append({"title": title, "isbn": isbn})
        else:
            return jsonify({"success": False, "error": "xlsx 또는 csv 파일만 업로드할 수 있습니다."})
    except Exception as exc:
        return jsonify({"success": False, "error": f"파일 처리 중 오류가 발생했습니다: {exc}"})

    CatalogBook.query.delete()
    for row in catalog_rows:
        title = row["title"].strip()
        if not title:
            continue
        db.session.add(
            CatalogBook(
                title=title,
                normalized_title=normalize_title(title),
                isbn=normalize_isbn(row.get("isbn", "")) or None,
            )
        )
    db.session.commit()

    return jsonify(
        {
            "success": True,
            "message": f"소장 도서 {len(catalog_rows)}권이 등록되었습니다.",
            "count": len(catalog_rows),
        }
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
