#!/usr/bin/env python3
"""Database management helpers for the Amcho Pasro Flask app (MongoDB).

Usage: python db_manager.py <command>

Commands:
  list_users    - List all users in the database
  create_user   - Create a new user (interactive)
  delete_user   - Delete a user by email
  reset_db      - Delete user-generated collections (users, products, reviews)
"""

from __future__ import annotations

import sys
from datetime import datetime
from getpass import getpass

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

try:
    from app import mongo_db, seed_default_categories, User
except Exception as exc:  # pragma: no cover - CLI helper
    print(f"Unable to import Flask app context: {exc}")
    sys.exit(1)


def list_users() -> None:
    """List all users with their key attributes."""
    users = list(mongo_db.users.find().sort("created_at", ASCENDING))
    if not users:
        print("No users found in MongoDB.")
        return
    print(f"\n{'ID':<25} {'Email':<30} {'Username':<20} {'Type':<8} {'Created'}")
    print("-" * 95)
    for doc in users:
        created = doc.get("created_at")
        created_str = created.strftime("%Y-%m-%d %H:%M") if isinstance(created, datetime) else "n/a"
        print(
            f"{str(doc.get('_id')):<25} "
            f"{doc.get('email', '-'):<30} "
            f"{doc.get('username', '-'):<20} "
            f"{doc.get('user_type', '-'):<8} "
            f"{created_str}"
        )
    print(f"\nTotal users: {len(users)}")


def create_user() -> None:
    """Create a new user interactively."""
    print("\n--- Create New User ---")
    username = input("Username: ").strip()
    email = input("Email: ").strip()
    password = getpass("Password: ").strip()
    user_type = input("User type (buyer/seller) [buyer]: ").strip().lower() or "buyer"

    if not username or not email or not password:
        print("Error: username, email, and password are required.")
        return
    if user_type not in {"buyer", "seller"}:
        print("Error: user type must be 'buyer' or 'seller'.")
        return
    extra_fields = {}
    if user_type == "seller":
        extra_fields["store_name"] = input("Store name: ").strip() or None
        extra_fields["store_location"] = input("Store location: ").strip() or None
        extra_fields["store_city"] = input("Store city: ").strip() or None

    if User.get_by_email(email):
        print(f"Error: user with email {email!r} already exists.")
        return

    doc = {
        "username": username,
        "email": email,
        "email_lower": User.normalize_email(email),
        "password_hash": generate_password_hash(password),
        "user_type": user_type,
        "created_at": datetime.utcnow(),
        **extra_fields,
    }

    try:
        result = mongo_db.users.insert_one(doc)
    except DuplicateKeyError:
        print(f"Error: user with email {email!r} already exists.")
        return

    print(f"Success: created user {username!r} with id {result.inserted_id}")


def delete_user() -> None:
    """Delete a user by email."""
    email = input("Enter email of user to delete: ").strip()
    if not email:
        print("Email is required.")
        return
    user = User.get_by_email(email)
    if not user:
        print(f"Error: No user found with email {email!r}.")
        return
    confirm = input(f"Are you sure you want to delete {user.username} ({email})? [y/N]: ")
    if confirm.lower() != "y":
        print("Deletion cancelled.")
        return
    mongo_db.users.delete_one({"_id": user.mongo_id})
    mongo_db.products.delete_many({"user_id": user.mongo_id})
    mongo_db.store_reviews.delete_many(
        {"$or": [{"store_owner_id": user.mongo_id}, {"reviewer_id": user.mongo_id}]}
    )
    print("User and related data deleted.")


def reset_db() -> None:
    """Reset user-generated collections (drops users, products, and store_reviews)."""
    confirm = input("This will DELETE all users, products, and reviews. Continue? [y/N]: ")
    if confirm.lower() != "y":
        print("Reset cancelled.")
        return
    mongo_db.users.delete_many({})
    mongo_db.products.delete_many({})
    mongo_db.store_reviews.delete_many({})
    seed_default_categories()
    print("Database reset. Default categories were re-seeded.")


def show_help() -> None:
    print(__doc__)


def main() -> None:
    if len(sys.argv) < 2:
        show_help()
        return
    command = sys.argv[1].lower()
    commands = {
        "list_users": list_users,
        "create_user": create_user,
        "delete_user": delete_user,
        "reset_db": reset_db,
        "help": show_help,
    }
    handler = commands.get(command)
    if not handler:
        print(f"Unknown command: {command}")
        show_help()
        return
    handler()


if __name__ == "__main__":
    main()
