from __future__ import annotations

import os
from datetime import datetime
from secrets import token_hex
from typing import Any, Dict, Iterable, List, Optional

import requests
from bson import ObjectId
from bson.errors import InvalidId
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", token_hex(32))

app.config["MONGODB_URI"] = os.environ.get(
    "MONGODB_URI",
    "mongodb://127.0.0.1:27017/amcho_pasro",
)
app.config["MONGODB_DB_NAME"] = os.environ.get("MONGODB_DB_NAME", "amcho_pasro")

mongo_client = MongoClient(app.config["MONGODB_URI"])
mongo_db = mongo_client[app.config["MONGODB_DB_NAME"]]

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "product_images"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "store_images"), exist_ok=True)

login_manager = LoginManager(app)
login_manager.login_view = "login"


def to_object_id(value: Any) -> Optional[ObjectId]:
    if isinstance(value, ObjectId):
        return value
    if value in (None, ""):
        return None
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


class MongoDocument:
    collection_name: str = ""

    def __init__(self, data: Optional[Dict[str, Any]] = None) -> None:
        self._data = data or {}

    def __getattr__(self, item: str) -> Any:
        if item == "id":
            _id = self._data.get("_id")
            return str(_id) if _id is not None else None
        value = self._data.get(item)
        if isinstance(value, ObjectId):
            return str(value)
        return value

    @property
    def mongo_id(self) -> Optional[ObjectId]:
        return self._data.get("_id")

    def refresh_from_db(self) -> None:
        coll = getattr(self.__class__, "collection", None)
        if not coll or not self.mongo_id:
            return
        fresh = coll.find_one({"_id": self.mongo_id})
        if fresh:
            self._data = fresh

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self._data)
        if "_id" in payload:
            payload["id"] = str(payload.pop("_id"))
        return payload


class User(UserMixin, MongoDocument):
    collection = mongo_db["users"]

    def get_id(self) -> Optional[str]:
        return str(self._data.get("_id")) if self._data.get("_id") else None

    @staticmethod
    def normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    @classmethod
    def get(cls, user_id: Any) -> Optional["User"]:
        oid = to_object_id(user_id)
        if not oid:
            return None
        doc = cls.collection.find_one({"_id": oid})
        return cls(doc) if doc else None

    @classmethod
    def get_by_email(cls, email: str) -> Optional["User"]:
        normalized = cls.normalize_email(email)
        if not normalized:
            return None
        doc = cls.collection.find_one({"email_lower": normalized})
        return cls(doc) if doc else None

    def is_seller(self) -> bool:
        return self._data.get("user_type") == "seller"

    def get_store_rating(self) -> Optional[float]:
        if not self.is_seller() or not self.mongo_id:
            return None
        pipeline = [
            {"$match": {"store_owner_id": self.mongo_id}},
            {
                "$group": {
                    "_id": "$store_owner_id",
                    "avg_rating": {"$avg": "$rating"},
                }
            },
        ]
        result = list(mongo_db.store_reviews.aggregate(pipeline))
        if not result:
            return None
        average = result[0].get("avg_rating")
        return round(float(average), 1) if average is not None else None

    def get_review_count(self) -> int:
        if not self.is_seller() or not self.mongo_id:
            return 0
        return mongo_db.store_reviews.count_documents({"store_owner_id": self.mongo_id})


class Category(MongoDocument):
    collection = mongo_db["categories"]

    @classmethod
    def all(cls) -> List["Category"]:
        return [cls(doc) for doc in cls.collection.find().sort("name", ASCENDING)]

    @classmethod
    def get(cls, category_id: Any) -> Optional["Category"]:
        oid = to_object_id(category_id)
        if not oid:
            return None
        doc = cls.collection.find_one({"_id": oid})
        return cls(doc) if doc else None

    @classmethod
    def get_by_slug(cls, slug: str) -> Optional["Category"]:
        if not slug:
            return None
        doc = cls.collection.find_one({"slug": slug})
        return cls(doc) if doc else None


class Product(MongoDocument):
    collection = mongo_db["products"]

    def __init__(self, data: Optional[Dict[str, Any]] = None, user: Optional[User] = None, category: Optional[Category] = None) -> None:
        super().__init__(data)
        self.user = user
        self.category = category
        timestamp = (data or {}).get("created_at") if data else None
        self.created_at = timestamp if isinstance(timestamp, datetime) else datetime.utcnow()

    @classmethod
    def get(cls, product_id: Any) -> Optional["Product"]:
        oid = to_object_id(product_id)
        if not oid:
            return None
        doc = cls.collection.find_one({"_id": oid})
        if not doc:
            return None
        return Product(
            doc,
            user=User.get(doc.get("user_id")),
            category=Category.get(doc.get("category_id")),
        )


class StoreReview(MongoDocument):
    collection = mongo_db["store_reviews"]

    def __init__(self, data: Optional[Dict[str, Any]] = None, reviewer: Optional[User] = None) -> None:
        super().__init__(data)
        self.reviewer = reviewer
        timestamp = (data or {}).get("created_at") if data else None
        self.created_at = timestamp if isinstance(timestamp, datetime) else datetime.utcnow()


def hydrate_products(product_docs: Iterable[Dict[str, Any]]) -> List[Product]:
    docs = list(product_docs)
    if not docs:
        return []
    user_ids = {doc.get("user_id") for doc in docs if doc.get("user_id")}
    category_ids = {doc.get("category_id") for doc in docs if doc.get("category_id")}
    users: Dict[ObjectId, User] = {}
    categories: Dict[ObjectId, Category] = {}
    if user_ids:
        user_cursor = mongo_db.users.find({"_id": {"$in": list(user_ids)}})
        users = {doc["_id"]: User(doc) for doc in user_cursor}
    if category_ids:
        category_cursor = mongo_db.categories.find({"_id": {"$in": list(category_ids)}})
        categories = {doc["_id"]: Category(doc) for doc in category_cursor}
    hydrated: List[Product] = []
    for doc in docs:
        user = users.get(doc.get("user_id"))
        if user is None and doc.get("user_id"):
            user = User(
                {
                    "_id": doc.get("user_id"),
                    "username": "Unknown seller",
                    "store_name": "Unknown store",
                    "user_type": "seller",
                }
            )
        hydrated.append(
            Product(
                doc,
                user=user,
                category=categories.get(doc.get("category_id")),
            )
        )
    return hydrated


def ensure_indexes() -> None:
    mongo_db.users.create_index("email_lower", unique=True)
    mongo_db.users.create_index("user_type")
    mongo_db.categories.create_index("slug", unique=True)
    mongo_db.products.create_index("created_at")
    mongo_db.products.create_index("user_id")
    mongo_db.products.create_index("category_id")
    mongo_db.store_reviews.create_index(
        [("store_owner_id", ASCENDING), ("reviewer_id", ASCENDING)],
        unique=True,
    )


def seed_default_categories() -> None:
    defaults = [
        ("Seafood", "seafood"),
        ("Handicrafts", "handicrafts"),
        ("Spices", "spices"),
        ("Organic Produce", "organic-produce"),
        ("Beverages", "beverages"),
        ("Art", "art"),
        ("Clothing", "clothing"),
        ("Other", "other"),
    ]
    for name, slug in defaults:
        mongo_db.categories.update_one(
            {"slug": slug},
            {
                "$setOnInsert": {
                    "name": name,
                    "slug": slug,
                    "created_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )


try:
    ensure_indexes()
    seed_default_categories()
except Exception as exc:  # pragma: no cover - best effort startup
    app.logger.warning("Unable to prepare MongoDB collections: %s", exc)


@app.context_processor
def inject_globals() -> Dict[str, Any]:
    return {"current_year": datetime.utcnow().year}


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return User.get(user_id)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def resolve_store_image_path(user: User) -> str:
    filename = user.store_image
    if not filename or filename == "default_store_img.png":
        rel_path = "images/default_store_img.png"
    elif str(filename).startswith(("uploads/", "images/")):
        rel_path = filename
    else:
        rel_path = f"uploads/{str(filename).lstrip('/')}"
    return url_for("static", filename=rel_path)


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("products"))
    sellers = mongo_db.users.find({"user_type": "seller"})
    stores = []
    for doc in sellers:
        user = User(doc)
        if user.store_latitude is None or user.store_longitude is None:
            continue
        stores.append(
            {
                "id": user.id,
                "name": user.store_name or user.username,
                "city": user.store_city,
                "location": user.store_location,
                "lat": user.store_latitude,
                "lng": user.store_longitude,
                "image": resolve_store_image_path(user),
            }
        )
    return render_template("index.html", stores=stores)


def resolve_category_from_query(raw_value: Optional[str]) -> Optional[Category]:
    if not raw_value:
        return None
    category = Category.get(raw_value)
    if category:
        return category
    return Category.get_by_slug(raw_value)


def score_product_for_query(product_doc: Dict[str, Any], query: str) -> float:
    title = (product_doc.get("title") or "").lower()
    desc = (product_doc.get("description") or "").lower()
    q_lower = query.lower()
    score = 0.0
    if q_lower in title:
        score += 100
        if title == q_lower:
            score += 50
    if q_lower in desc:
        score += 30
    created = product_doc.get("created_at")
    if isinstance(created, datetime):
        age_days = (datetime.utcnow() - created).days
        score += max(0, 20 - age_days)
    return score


@app.route("/products")
@login_required
def products():
    search_query = request.args.get("q", "").strip()
    category_filter = request.args.get("category")
    current_category = resolve_category_from_query(category_filter)

    mongo_query: Dict[str, Any] = {}
    if current_category and current_category.mongo_id:
        mongo_query["category_id"] = current_category.mongo_id
    if search_query:
        regex = {"$regex": search_query, "$options": "i"}
        mongo_query["$or"] = [{"title": regex}, {"description": regex}]

    cursor = mongo_db.products.find(mongo_query)
    if not search_query:
        cursor = cursor.sort("created_at", DESCENDING)
    docs = list(cursor)
    if search_query:
        docs.sort(key=lambda doc: score_product_for_query(doc, search_query), reverse=True)
    products_list = hydrate_products(docs)
    categories = Category.all()
    return render_template(
        "products.html",
        products=products_list,
        categories=categories,
        current_category=current_category,
    )


@app.route("/categories")
@login_required
def categories_page():
    categories = Category.all()
    for cat in categories:
        cat.product_count = mongo_db.products.count_documents({"category_id": cat.mongo_id})
    return render_template("categories.html", categories=categories)


@app.route("/category/<slug>")
@login_required
def category_detail(slug: str):
    category = Category.get_by_slug(slug)
    if not category:
        flash("Category not found", "error")
        return redirect(url_for("categories_page"))
    docs = mongo_db.products.find({"category_id": category.mongo_id}).sort("created_at", DESCENDING)
    products_list = hydrate_products(docs)
    categories = Category.all()
    return render_template(
        "products.html",
        products=products_list,
        categories=categories,
        current_category=category,
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("products"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = User.get_by_email(email)
        if user and check_password_hash(user._data.get("password_hash", ""), password):
            login_user(user)
            next_page = request.args.get("next")
            flash("Successfully logged in!", "success")
            return redirect(next_page or url_for("products"))
        flash("Invalid email or password", "error")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("products"))
    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip()
        last_name = request.form.get("lastName", "").strip()
        username = f"{first_name} {last_name}".strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirmPassword", "")
        if not first_name or not last_name or not email or not password:
            flash("All fields are required", "error")
        elif password != confirm_password:
            flash("Passwords do not match", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long", "error")
        elif User.get_by_email(email):
            flash("An account with this email already exists", "error")
        else:
            doc = {
                "username": username,
                "email": email,
                "email_lower": User.normalize_email(email),
                "password_hash": generate_password_hash(password),
                "user_type": "buyer",
                "created_at": datetime.utcnow(),
            }
            try:
                insert_result = mongo_db.users.insert_one(doc)
                doc["_id"] = insert_result.inserted_id
                flash("Account created successfully! Please log in.", "success")
                return redirect(url_for("login"))
            except DuplicateKeyError:
                flash("An account with this email already exists", "error")
    return render_template("signup.html")


@app.route("/seller-signup", methods=["GET", "POST"])
def seller_signup():
    if current_user.is_authenticated:
        return redirect(url_for("products"))
    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip()
        last_name = request.form.get("lastName", "").strip()
        username = f"{first_name} {last_name}".strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirmPassword", "")
        store_name = request.form.get("storeName", "").strip()
        store_location = request.form.get("storeLocation", "").strip()
        store_city = request.form.get("storeCity", "").strip()
        image_file = request.files.get("storeImage")
        lat_raw = request.form.get("latitude")
        lng_raw = request.form.get("longitude")
        addr_full = request.form.get("address", "").strip()
        try:
            store_lat = float(lat_raw) if lat_raw not in (None, "") else None
        except ValueError:
            store_lat = None
        try:
            store_lng = float(lng_raw) if lng_raw not in (None, "") else None
        except ValueError:
            store_lng = None
        if addr_full and not store_location:
            store_location = addr_full[:200]
        if not all([first_name, last_name, email, password, store_name, store_location, store_city]):
            flash("All fields are required", "error")
        elif password != confirm_password:
            flash("Passwords do not match", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long", "error")
        elif User.get_by_email(email):
            flash("An account with this email already exists", "error")
        else:
            store_image = None
            if image_file and image_file.filename and allowed_file(image_file.filename):
                store_img_folder = os.path.join(app.config["UPLOAD_FOLDER"], "store_images")
                os.makedirs(store_img_folder, exist_ok=True)
                filename = secure_filename(image_file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
                filename = timestamp + filename
                image_file.save(os.path.join(store_img_folder, filename))
                store_image = f"store_images/{filename}"
            doc = {
                "username": username,
                "email": email,
                "email_lower": User.normalize_email(email),
                "password_hash": generate_password_hash(password),
                "user_type": "seller",
                "store_name": store_name,
                "store_location": store_location,
                "store_city": store_city,
                "store_latitude": store_lat,
                "store_longitude": store_lng,
                "store_address": addr_full or None,
                "store_image": store_image,
                "created_at": datetime.utcnow(),
            }
            try:
                mongo_db.users.insert_one(doc)
                flash("Seller account created successfully! Please log in.", "success")
                return redirect(url_for("login"))
            except DuplicateKeyError:
                flash("An account with this email already exists", "error")
    return render_template("seller-signup.html")


@app.route("/post-product", methods=["GET", "POST"])
@login_required
def post_product():
    if not current_user.is_seller():
        flash("Only sellers can post products. Please register as a seller.", "error")
        return redirect(url_for("index"))
    categories = Category.all()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        price = request.form.get("price", "")
        quantity = request.form.get("quantity", "1")
        description = request.form.get("description", "").strip()
        category_raw = request.form.get("category")
        image_filename = None
        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                prod_img_folder = os.path.join(app.config["UPLOAD_FOLDER"], "product_images")
                os.makedirs(prod_img_folder, exist_ok=True)
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
                filename = timestamp + filename
                file.save(os.path.join(prod_img_folder, filename))
                image_filename = f"product_images/{filename}"
        if not title or not price:
            flash("Title and price are required fields", "error")
        else:
            try:
                price_float = float(price)
                quantity_int = int(quantity) if quantity else 1
                if price_float <= 0:
                    flash("Price must be greater than 0", "error")
                elif quantity_int <= 0:
                    flash("Quantity must be greater than 0", "error")
                else:
                    category_id = None
                    if category_raw:
                        resolved_category = resolve_category_from_query(category_raw)
                        if resolved_category and resolved_category.mongo_id:
                            category_id = resolved_category.mongo_id
                    doc = {
                        "title": title,
                        "price": price_float,
                        "quantity": quantity_int,
                        "description": description,
                        "image_filename": image_filename,
                        "user_id": current_user.mongo_id,
                        "category_id": category_id,
                        "created_at": datetime.utcnow(),
                    }
                    mongo_db.products.insert_one(doc)
                    flash("Product posted successfully!", "success")
                    return redirect(url_for("products"))
            except ValueError:
                flash("Please enter valid numbers for price and quantity", "error")
    return render_template("post-product.html", categories=categories)


@app.route("/product/<string:product_id>")
@login_required
def product_detail(product_id: str):
    product = Product.get(product_id)
    if not product:
        abort(404)
    return render_template("product-detail.html", product=product)


@app.route("/my-store")
@login_required
def my_store():
    if not current_user.is_seller():
        flash("You don't have a store. Register as a seller to create one.", "error")
        return redirect(url_for("products"))
    return redirect(url_for("store_page", store_owner_id=current_user.id))


@app.route("/edit-store", methods=["GET", "POST"])
@login_required
def edit_store():
    if not current_user.is_seller():
        flash("Only sellers can edit store details.", "error")
        return redirect(url_for("products"))
    user = current_user
    if request.method == "POST":
        store_name = request.form.get("store_name", "").strip()
        store_location = request.form.get("store_location", "").strip()
        store_city = request.form.get("store_city", "").strip()
        lat_raw = request.form.get("latitude")
        lng_raw = request.form.get("longitude")
        addr_full = request.form.get("address", "").strip()
        image_file = request.files.get("store_image")
        try:
            store_lat = float(lat_raw) if lat_raw not in (None, "") else None
        except ValueError:
            store_lat = None
        try:
            store_lng = float(lng_raw) if lng_raw not in (None, "") else None
        except ValueError:
            store_lng = None
        update_doc: Dict[str, Any] = {}
        if store_name:
            update_doc["store_name"] = store_name
        if store_location:
            update_doc["store_location"] = store_location
        if store_city:
            update_doc["store_city"] = store_city
        if addr_full:
            update_doc["store_address"] = addr_full
        if store_lat is not None:
            update_doc["store_latitude"] = store_lat
        if store_lng is not None:
            update_doc["store_longitude"] = store_lng
        if image_file and image_file.filename and allowed_file(image_file.filename):
            store_img_folder = os.path.join(app.config["UPLOAD_FOLDER"], "store_images")
            os.makedirs(store_img_folder, exist_ok=True)
            filename = secure_filename(image_file.filename)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
            filename = timestamp + filename
            image_file.save(os.path.join(store_img_folder, filename))
            update_doc["store_image"] = f"store_images/{filename}"
        if update_doc:
            mongo_db.users.update_one({"_id": user.mongo_id}, {"$set": update_doc})
            user.refresh_from_db()
            flash("Store details updated successfully!", "success")
            return redirect(url_for("my_store"))
    return render_template("edit-store.html", user=user)


@app.route("/store/<string:store_owner_id>")
@login_required
def store_page(store_owner_id: str):
    store_owner = User.get(store_owner_id)
    if not store_owner:
        abort(404)
    if not store_owner.is_seller():
        flash("This user is not a store owner", "error")
        return redirect(url_for("products"))
    products_cursor = mongo_db.products.find({"user_id": store_owner.mongo_id}).sort("created_at", DESCENDING)
    products_list = hydrate_products(products_cursor)
    reviews_cursor = mongo_db.store_reviews.find({"store_owner_id": store_owner.mongo_id}).sort("created_at", DESCENDING)
    review_docs = list(reviews_cursor)
    reviewer_ids = {doc.get("reviewer_id") for doc in review_docs if doc.get("reviewer_id")}
    reviewers: Dict[ObjectId, User] = {}
    if reviewer_ids:
        reviewer_cursor = mongo_db.users.find({"_id": {"$in": list(reviewer_ids)}})
        reviewers = {doc["_id"]: User(doc) for doc in reviewer_cursor}
    reviews = [StoreReview(doc, reviewer=reviewers.get(doc.get("reviewer_id"))) for doc in review_docs]
    existing_review = None
    if current_user.is_authenticated and current_user.mongo_id and current_user.id != store_owner.id:
        doc = mongo_db.store_reviews.find_one(
            {"store_owner_id": store_owner.mongo_id, "reviewer_id": current_user.mongo_id}
        )
        if doc:
            existing_review = StoreReview(doc, reviewer=current_user)
    return render_template(
        "store-page.html",
        store_owner=store_owner,
        products=products_list,
        reviews=reviews,
        existing_review=existing_review,
    )


@app.route("/stores")
@login_required
def store_finder():
    sellers = mongo_db.users.find({"user_type": "seller"})
    stores = []
    for doc in sellers:
        user = User(doc)
        stores.append(
            {
                "id": user.id,
                "name": user.store_name or user.username,
                "city": user.store_city,
                "location": user.store_location,
                "address": user.store_address,
                "lat": user.store_latitude,
                "lng": user.store_longitude,
                "rating": user.get_store_rating(),
                "reviews": user.get_review_count(),
                "product_count": mongo_db.products.count_documents({"user_id": user.mongo_id}),
                "image": resolve_store_image_path(user),
            }
        )
    return render_template("store-finder.html", stores=stores)


@app.route("/store/<string:store_owner_id>/review", methods=["POST"])
@login_required
def add_store_review(store_owner_id: str):
    store_owner = User.get(store_owner_id)
    if not store_owner:
        abort(404)
    if current_user.id == store_owner.id:
        flash("You cannot review your own store", "error")
        return redirect(url_for("store_page", store_owner_id=store_owner_id))
    rating_raw = request.form.get("rating")
    review_text = request.form.get("review_text", "").strip()
    if not rating_raw:
        flash("Rating is required", "error")
        return redirect(url_for("store_page", store_owner_id=store_owner_id))
    try:
        rating = int(rating_raw)
    except ValueError:
        flash("Invalid rating value", "error")
        return redirect(url_for("store_page", store_owner_id=store_owner_id))
    if rating < 1 or rating > 5:
        flash("Rating must be between 1 and 5", "error")
        return redirect(url_for("store_page", store_owner_id=store_owner_id))
    existing = mongo_db.store_reviews.find_one(
        {"store_owner_id": store_owner.mongo_id, "reviewer_id": current_user.mongo_id}
    )
    payload = {
        "store_owner_id": store_owner.mongo_id,
        "reviewer_id": current_user.mongo_id,
        "rating": rating,
        "review_text": review_text,
        "created_at": datetime.utcnow(),
    }
    if existing:
        mongo_db.store_reviews.update_one({"_id": existing["_id"]}, {"$set": payload})
        flash("Your review has been updated", "success")
    else:
        mongo_db.store_reviews.insert_one(payload)
        flash("Your review has been added", "success")
    return redirect(url_for("store_page", store_owner_id=store_owner_id))


@app.route("/api/geocode/search")
def geocode_search():
    q = request.args.get("q", "").strip()
    limit = request.args.get("limit", "8")
    if not q or len(q) < 2:
        return jsonify([])
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q,
                "format": "jsonv2",
                "limit": limit,
                "addressdetails": 1,
            },
            headers={
                "User-Agent": "AmchoPasroApp/1.0 (+http://localhost)",
                "Accept": "application/json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return jsonify([]), resp.status_code
        return jsonify(resp.json())
    except Exception:
        return jsonify([]), 502


@app.route("/api/geocode/reverse")
def geocode_reverse():
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    if lat is None or lon is None:
        return jsonify({}), 400
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat,
                "lon": lon,
                "zoom": 14,
                "addressdetails": 1,
            },
            headers={
                "User-Agent": "AmchoPasroApp/1.0 (+http://localhost)",
                "Accept": "application/json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return jsonify({}), resp.status_code
        return jsonify(resp.json())
    except Exception:
        return jsonify({}), 502


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out", "info")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
