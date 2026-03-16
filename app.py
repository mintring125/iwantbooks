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
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "purchase-wishlist-2026")
app.config["SQLALCHEMY_DATABASE_URI"] = build_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

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
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "신청결과"

    headers = [
        "제출시각",
        "학년",
        "반",
        "번호",
        "학생표시",
        "1지망 도서명",
        "1지망 저자",
        "1지망 출판사",
        "1지망 가격",
        "2지망 도서명",
        "2지망 저자",
        "2지망 출판사",
        "2지망 가격",
        "3지망 도서명",
        "3지망 저자",
        "3지망 출판사",
        "3지망 가격",
    ]
    worksheet.append(headers)

    header_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    header_font = Font(bold=True)
    thin_border = build_border()
    center_align = Alignment(horizontal="center", vertical="center")

    for index, header in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=index, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = center_align

    for submission in submissions:
        row = [
            submission["timestamp"],
            submission["grade"],
            submission["classNum"],
            submission["studentNumber"],
            submission["studentLabel"],
        ]
        books = submission["books"]
        for book_index in range(3):
            book = books[book_index] if book_index < len(books) else {}
            row.extend(
                [
                    book.get("title", ""),
                    book.get("author", ""),
                    book.get("publisher", ""),
                    book.get("price", 0),
                ]
            )
        worksheet.append(row)

    for row in worksheet.iter_rows():
        for cell in row:
            cell.border = thin_border

    widths = {
        "A": 20,
        "B": 8,
        "C": 8,
        "D": 8,
        "E": 18,
        "F": 28,
        "G": 16,
        "H": 18,
        "I": 10,
        "J": 28,
        "K": 16,
        "L": 18,
        "M": 10,
        "N": 28,
        "O": 16,
        "P": 18,
        "Q": 10,
    }
    for column, width in widths.items():
        worksheet.column_dimensions[column].width = width

    return workbook


def require_admin():
    return session.get("is_admin") is True


def query_submissions(grade="", class_num=""):
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
    with app.app_context():
        db.create_all()
        bootstrap_submissions_from_json()
        bootstrap_catalog_from_json()


@app.route("/")
def index():
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
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401

    grade = request.args.get("grade", "").strip()
    class_num = request.args.get("classNum", "").strip()
    return jsonify({"submissions": query_submissions(grade=grade, class_num=class_num)})


@app.route("/api/admin/export")
def admin_export():
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
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401
    books = CatalogBook.query.order_by(CatalogBook.title.asc()).all()
    return jsonify({"catalog": [book.to_dict() for book in books]})


@app.route("/api/admin/catalog", methods=["DELETE"])
def clear_catalog():
    if not require_admin():
        return jsonify({"error": "관리자 인증이 필요합니다."}), 401
    CatalogBook.query.delete()
    db.session.commit()
    return jsonify({"success": True})


@app.route("/api/admin/upload-catalog", methods=["POST"])
def upload_catalog():
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


initialize_database()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
