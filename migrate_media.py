#!/usr/bin/env python3
"""One-time helper to move existing product/store images into MongoDB GridFS.

Usage examples:
  python migrate_media.py             # migrates and updates documents
  python migrate_media.py --dry-run   # just reports what would change
"""

from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from gridfs import GridFS
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "static" / "uploads"
DEFAULT_STORE_IMAGE = "images/default_store_img.png"


def to_object_id(value: Optional[str]) -> Optional[ObjectId]:
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def resolve_local_path(rel_path: str) -> Optional[Path]:
    """Return absolute path for a legacy upload reference, if the file exists."""

    if not rel_path:
        return None
    cleaned = rel_path.strip().lstrip("/")
    candidates = [cleaned]
    if not cleaned.startswith("uploads/"):
        candidates.append(f"uploads/{cleaned}")
    for candidate in candidates:
        absolute = BASE_DIR / "static" / candidate
        if absolute.exists() and absolute.is_file():
            return absolute
    return None


def store_file(fs: GridFS, path: Path, *, owner_id: Optional[ObjectId], usage: str, dry_run: bool) -> Optional[ObjectId]:
    if dry_run:
        return ObjectId()  # dummy placeholder
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    metadata = {"usage": usage}
    if owner_id:
        metadata["owner_id"] = owner_id
    with path.open("rb") as handle:
        media_id = fs.put(handle.read(), filename=path.name, content_type=mimetype, metadata=metadata)
    return to_object_id(media_id)


def migrate_store_images(db, fs: GridFS, dry_run: bool) -> int:
    migrated = 0
    sellers = db.users.find({
        "user_type": "seller",
        "store_image_media_id": {"$exists": False},
        "store_image": {"$nin": [None, "", DEFAULT_STORE_IMAGE]},
    })
    for seller in sellers:
        rel_path = seller.get("store_image")
        local_path = resolve_local_path(rel_path or "")
        if not local_path:
            print(f"[SKIP store] Missing file for seller {seller.get('_id')} ({rel_path})")
            continue
        media_id = store_file(fs, local_path, owner_id=seller.get("_id"), usage="store-avatar", dry_run=dry_run)
        if not media_id:
            print(f"[SKIP store] Failed to store file for seller {seller.get('_id')}")
            continue
        update_ops = {"$set": {"store_image_media_id": media_id}}
        update_ops["$unset"] = {"store_image": ""}
        if dry_run:
            print(f"[DRY-RUN store] Would migrate {local_path} -> GridFS for seller {seller.get('_id')}")
        else:
            db.users.update_one({"_id": seller.get("_id")}, update_ops)
            print(f"[store] Migrated {local_path} -> media {media_id}")
        migrated += 1
    return migrated


def migrate_product_images(db, fs: GridFS, dry_run: bool) -> int:
    migrated = 0
    products = db.products.find({
        "image_media_id": {"$exists": False},
        "image_filename": {"$nin": [None, ""]},
    })
    for product in products:
        rel_path = product.get("image_filename")
        local_path = resolve_local_path(rel_path or "")
        if not local_path:
            print(f"[SKIP product] Missing file for product {product.get('_id')} ({rel_path})")
            continue
        media_id = store_file(fs, local_path, owner_id=product.get("user_id"), usage="product-image", dry_run=dry_run)
        if not media_id:
            print(f"[SKIP product] Failed to store file for product {product.get('_id')}")
            continue
        update_ops = {"$set": {"image_media_id": media_id}, "$unset": {"image_filename": ""}}
        if dry_run:
            print(f"[DRY-RUN product] Would migrate {local_path} -> GridFS for product {product.get('_id')}")
        else:
            db.products.update_one({"_id": product.get("_id")}, update_ops)
            print(f"[product] Migrated {local_path} -> media {media_id}")
        migrated += 1
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate existing media files into MongoDB GridFS.")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing to MongoDB")
    args = parser.parse_args()

    load_dotenv()
    mongo_uri = os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017/amcho_pasro")
    db_name = os.environ.get("MONGODB_DB_NAME", "amcho_pasro")

    if not UPLOADS_DIR.exists():
        print(f"Warning: uploads directory {UPLOADS_DIR} does not exist. Continuing anyway...")

    client = MongoClient(mongo_uri)
    db = client[db_name]
    fs = GridFS(db, collection="media_files")

    stores = migrate_store_images(db, fs, args.dry_run)
    products = migrate_product_images(db, fs, args.dry_run)

    print("--- Summary ---")
    print(f"Stores processed: {stores}")
    print(f"Products processed: {products}")
    if args.dry_run:
        print("Dry-run complete. Re-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
