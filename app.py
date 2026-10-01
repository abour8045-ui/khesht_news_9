from __future__ import annotations

import argparse
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from PIL import Image
from sqlalchemy import or_
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
IMAGE_DIR = BASE_DIR / "uploads" / "images"
VIDEO_DIR = BASE_DIR / "uploads" / "videos"
FONT_DIR = BASE_DIR / "static" / "fonts"
LOGO_PATH = BASE_DIR / "static" / "images" / "logo.png"
TOP_BANNER_DIR = BASE_DIR / "static" / "images"
TOP_BANNER_NAMES = ("top-banner.png", "top-banner.jpg", "top-banner.jpeg", "top-banner.webp")
DB_PATH = INSTANCE_DIR / "khesht_news.db"

ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}
ALLOWED_VIDEO_EXT = {"mp4", "webm", "mov"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
FONT_PRIORITY = {"woff2": 0, "woff": 1, "ttf": 2, "otf": 3}
REPORTER_CODE = "442233836696"


db = SQLAlchemy()
csrf = CSRFProtect()


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    news = db.relationship("News", back_populates="category", lazy=True)


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False)
    slug = db.Column(db.String(240), nullable=False, default="")
    summary = db.Column(db.Text, nullable=False, default="")
    body = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="draft")
    image_filename = db.Column(db.String(300), nullable=True)
    video_filename = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    published_at = db.Column(db.DateTime, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    category = db.relationship("Category", back_populates="news")
    images = db.relationship("NewsImage", back_populates="news", cascade="all, delete-orphan", lazy=True)


class NewsImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    news_id = db.Column(db.Integer, db.ForeignKey("news.id"), nullable=False)
    news = db.relationship("News", back_populates="images")


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


def create_app():
    app = Flask(__name__, instance_path=str(INSTANCE_DIR), instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("KHESHT_SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("KHESHT_SECURE_COOKIE", "0") == "1",
    )
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "static" / "images").mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        db.create_all()
        seed_categories()

    register_template_helpers(app)
    register_routes(app)
    register_errors(app)
    return app


def seed_categories():
    categories = [
        ("اخبار خشت", "khesht"), ("شهرستان", "city"), ("استان", "province"),
        ("جامعه", "society"), ("فرهنگ", "culture"), ("ورزش", "sports"),
        ("اقتصاد", "economy"), ("حوادث", "accidents"), ("آموزش", "education"),
        ("سایر", "other"),
    ]
    changed = False
    for name, slug in categories:
        if not Category.query.filter_by(slug=slug).first():
            db.session.add(Category(name=name, slug=slug))
            changed = True
    if changed:
        db.session.commit()


def register_template_helpers(app):
    @app.context_processor
    def inject_globals():
        font = detect_font()
        top_banner = next((TOP_BANNER_DIR / name for name in TOP_BANNER_NAMES if (TOP_BANNER_DIR / name).is_file()), None)
        return {
            "site_name": "خشت نیوز",
            "site_logo_exists": LOGO_PATH.is_file() and LOGO_PATH.stat().st_size > 0,
            "top_banner_url": url_for("static", filename=f"images/{top_banner.name}") if top_banner else None,
            "font_url": font,
            "is_admin": bool(session.get("admin_id")),
            "year_now": datetime.now().year,
            "categories_for_footer": Category.query.order_by(Category.id).all(),
        }

    @app.template_filter("localdate")
    def localdate(value):
        if not value:
            return ""
        return value.astimezone().strftime("%Y/%m/%d") if value.tzinfo else value.strftime("%Y/%m/%d")

    @app.template_filter("localtime")
    def localtime(value):
        if not value:
            return ""
        return value.astimezone().strftime("%H:%M") if value.tzinfo else value.strftime("%H:%M")

    @app.template_filter("plain_text")
    def plain_text(value):
        return re.sub(r"\s+", " ", value or "").strip()


def detect_font():
    font_path = FONT_DIR / "Lyon Arabic Display Bold.ttf"
    if font_path.is_file():
        return url_for("static", filename="fonts/Lyon%20Arabic%20Display%20Bold.ttf")
    fonts = [p for p in FONT_DIR.iterdir() if p.is_file() and p.suffix.lower().lstrip(".") in FONT_PRIORITY]
    if not fonts:
        return None
    fonts.sort(key=lambda p: (FONT_PRIORITY[p.suffix.lower().lstrip(".")], p.name.lower()))
    return url_for("static", filename=f"fonts/{quote(fonts[0].name)}")


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\u0600-\u06ff\u200c-\u200f -]", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:220] or "news"


def unique_slug(title: str, current_id: int | None = None) -> str:
    base = slugify(title)
    slug = base
    n = 2
    while True:
        q = News.query.filter_by(slug=slug)
        if current_id:
            q = q.filter(News.id != current_id)
        if not q.first():
            return slug
        slug = f"{base}-{n}"
        n += 1


def admin_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("admin_id") != "reporter":
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_upload(file_storage, directory: Path, allowed_ext: set[str], kind: str) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    original = secure_filename(file_storage.filename)
    ext = Path(original).suffix.lower().lstrip(".")
    if ext not in allowed_ext:
        raise ValueError(f"فرمت {kind} مجاز نیست.")
    if file_storage.content_length and file_storage.content_length > MAX_UPLOAD_BYTES:
        raise ValueError("حجم فایل بیشتر از حد مجاز است.")
    token = secrets.token_hex(16)
    filename = f"{token}.{ext}"
    destination = directory / filename
    file_storage.save(destination)
    if kind == "تصویر":
        try:
            with Image.open(destination) as img:
                img.verify()
        except Exception:
            destination.unlink(missing_ok=True)
            raise ValueError("فایل تصویر معتبر نیست.")
    return filename


def delete_file(directory: Path, filename: str | None):
    if not filename:
        return
    path = directory / Path(filename).name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def public_news_query():
    return News.query.filter_by(status="published").order_by(News.published_at.desc(), News.id.desc())


def register_routes(app):
    @app.get("/")
    def index():
        latest = public_news_query().limit(12).all()
        featured = public_news_query().limit(3).all()
        categories = Category.query.order_by(Category.id).all()
        videos = public_news_query().filter(News.video_filename.is_not(None)).limit(4).all()
        return render_template("index.html", latest=latest, featured=featured, categories=categories, videos=videos)

    @app.get("/news/<int:news_id>-<slug>")
    def news_detail(news_id, slug):
        news = db.session.get(News, news_id)
        if not news or news.status != "published":
            abort(404)
        related = public_news_query().filter(News.category_id == news.category_id, News.id != news.id).limit(4).all()
        return render_template("news.html", news=news, related=related)

    @app.get("/category/<slug>")
    def category(slug):
        cat = Category.query.filter_by(slug=slug).first_or_404()
        items = public_news_query().filter_by(category_id=cat.id).all()
        return render_template("category.html", category=cat, news_items=items)

    @app.get("/search")
    def search():
        q = request.args.get("q", "").strip()
        items = []
        if q:
            pattern = f"%{q}%"
            items = public_news_query().filter(or_(News.title.ilike(pattern), News.summary.ilike(pattern), News.body.ilike(pattern))).all()
        return render_template("search.html", q=q, news_items=items)

    @app.get("/uploads/images/<path:filename>")
    def uploaded_image(filename):
        from flask import send_from_directory
        return send_from_directory(IMAGE_DIR, Path(filename).name)

    @app.get("/uploads/videos/<path:filename>")
    def uploaded_video(filename):
        from flask import send_from_directory
        return send_from_directory(VIDEO_DIR, Path(filename).name)

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("admin_id") == "reporter":
            return redirect(url_for("admin_dashboard"))
        if request.method == "POST":
            access_code = request.form.get("access_code", "").strip()
            if access_code == REPORTER_CODE:
                session.clear()
                session["admin_id"] = "reporter"
                session.permanent = True
                return redirect(request.args.get("next") or url_for("admin_dashboard"))
            flash("کد ورود نادرست است.", "error")
        return render_template("admin/login.html")
    @app.post("/admin/logout")
    @admin_required
    def admin_logout():
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        total = News.query.count()
        published = News.query.filter_by(status="published").count()
        drafts = News.query.filter_by(status="draft").count()
        categories_count = Category.query.count()
        recent = News.query.order_by(News.created_at.desc(), News.id.desc()).limit(8).all()
        return render_template("admin/dashboard.html", total=total, published=published, drafts=drafts, categories_count=categories_count, recent=recent)

    @app.get("/admin/news")
    @admin_required
    def admin_news_list():
        q = request.args.get("q", "").strip()
        category_id = request.args.get("category_id", type=int)
        query = News.query.order_by(News.created_at.desc(), News.id.desc())
        if q:
            pattern = f"%{q}%"
            query = query.filter(or_(News.title.ilike(pattern), News.summary.ilike(pattern)))
        if category_id:
            query = query.filter_by(category_id=category_id)
        return render_template("admin/news_list.html", news_items=query.all(), categories=Category.query.order_by(Category.id).all(), q=q, category_id=category_id)

    @app.route("/admin/news/new", methods=["GET", "POST"])
    @admin_required
    def admin_news_new():
        categories = Category.query.order_by(Category.id).all()
        if request.method == "POST":
            try:
                news = save_news_from_form(None)
                db.session.add(news)
                db.session.flush()
                save_additional_images(news)
                db.session.commit()
                flash("خبر با موفقیت ایجاد شد.", "success")
                return redirect(url_for("admin_news_list"))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template("admin/news_form.html", news=None, categories=categories, form_title="افزودن خبر")

    @app.route("/admin/news/<int:news_id>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_news_edit(news_id):
        news = db.session.get(News, news_id) or abort(404)
        categories = Category.query.order_by(Category.id).all()
        if request.method == "POST":
            try:
                old_image = news.image_filename
                old_video = news.video_filename
                save_news_from_form(news)
                if old_image != news.image_filename:
                    delete_file(IMAGE_DIR, old_image)
                if old_video != news.video_filename:
                    delete_file(VIDEO_DIR, old_video)
                save_additional_images(news)
                db.session.commit()
                flash("خبر با موفقیت ویرایش شد.", "success")
                return redirect(url_for("admin_news_list"))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template("admin/news_form.html", news=news, categories=categories, form_title="ویرایش خبر")

    @app.post("/admin/news/<int:news_id>/delete")
    @admin_required
    def admin_news_delete(news_id):
        news = db.session.get(News, news_id) or abort(404)
        delete_file(IMAGE_DIR, news.image_filename)
        delete_file(VIDEO_DIR, news.video_filename)
        for image in news.images:
            delete_file(IMAGE_DIR, image.filename)
        db.session.delete(news)
        db.session.commit()
        flash("خبر حذف شد.", "success")
        return redirect(url_for("admin_news_list"))

    @app.post("/admin/news/<int:news_id>/delete-image/<int:image_id>")
    @admin_required
    def admin_delete_image(news_id, image_id):
        image = NewsImage.query.filter_by(id=image_id, news_id=news_id).first_or_404()
        delete_file(IMAGE_DIR, image.filename)
        db.session.delete(image)
        db.session.commit()
        flash("تصویر حذف شد.", "success")
        return redirect(url_for("admin_news_edit", news_id=news_id))


def save_news_from_form(news: News | None) -> News:
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    body = request.form.get("body", "").strip()
    category_id = request.form.get("category_id", type=int)
    status = request.form.get("status", "draft")
    if not title or not body or not category_id:
        raise ValueError("عنوان، متن کامل و دسته‌بندی الزامی هستند.")
    if status not in {"draft", "published"}:
        status = "draft"
    if news is None:
        news = News(title=title, slug=unique_slug(title), summary=summary, body=body, category_id=category_id, status=status)
    else:
        news.title = title
        news.slug = unique_slug(title, news.id)
        news.summary = summary
        news.body = body
        news.category_id = category_id
        news.status = status

    image = request.files.get("image")
    if image and image.filename:
        new_image = safe_upload(image, IMAGE_DIR, ALLOWED_IMAGE_EXT, "تصویر")
        old = news.image_filename
        news.image_filename = new_image
        if old and old != new_image:
            delete_file(IMAGE_DIR, old)

    video = request.files.get("video")
    if video and video.filename:
        new_video = safe_upload(video, VIDEO_DIR, ALLOWED_VIDEO_EXT, "ویدیو")
        old = news.video_filename
        news.video_filename = new_video
        if old and old != new_video:
            delete_file(VIDEO_DIR, old)

    if status == "published" and not news.published_at:
        news.published_at = datetime.now(timezone.utc)
    if status == "draft":
        news.published_at = None
    return news


def save_additional_images(news: News):
    for file_storage in request.files.getlist("additional_images"):
        if not file_storage or not file_storage.filename:
            continue
        filename = safe_upload(file_storage, IMAGE_DIR, ALLOWED_IMAGE_EXT, "تصویر")
        db.session.add(NewsImage(filename=filename, news=news))


def register_errors(app):
    @app.errorhandler(413)
    def too_large(_):
        flash("حجم فایل بیشتر از ۶۴ مگابایت است.", "error")
        return redirect(request.referrer or url_for("admin_dashboard"))

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("500.html"), 500


def create_admin(username: str, password: str):
    app = create_app()
    with app.app_context():
        if Admin.query.filter_by(username=username).first():
            print("این نام کاربری از قبل وجود دارد.")
            return 1
        admin = Admin(username=username, password_hash=generate_password_hash(password))
        db.session.add(admin)
        db.session.commit()
        print(f"مدیر '{username}' با موفقیت ساخته شد.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khesht News Flask application")
    parser.add_argument("--create-admin", action="store_true", help="Create the first admin account interactively")
    args = parser.parse_args()
    if args.create_admin:
        import getpass
        username = input("Admin username: ").strip()
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if not username or not password or password != confirm:
            raise SystemExit("نام کاربری/رمز عبور نامعتبر است یا دو رمز یکسان نیستند.")
        raise SystemExit(create_admin(username, password))
    app = create_app()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
