## Amcho Pasro

The Flask marketplace now runs entirely on MongoDB (Atlas or self-hosted) instead of SQLite. The production deployment remains available at https://amcho-pasro.onrender.com.

### Running locally

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Set the MongoDB connection string** (Atlas SRV URI or local instance):
   ```bash
   set MONGODB_URI="your connection string"
   set MONGODB_DB_NAME=amcho_pasro  # optional override
   set FLASK_SECRET_KEY="replace-me"  # optional but recommended
   ```
3. **Start the app**
   ```bash
   flask --app app run --debug
   ```

The server auto-creates common indexes, seeds default categories, and stores uploads under `static/uploads`.

### MongoDB administration

Use `python db_manager.py <command>` for quick maintenance:

| Command       | Description                                           |
| ------------- | ----------------------------------------------------- |
| `list_users`  | Show every account with type and creation date.       |
| `create_user` | Interactive prompt to add a buyer or seller.          |
| `delete_user` | Remove a user plus their products and reviews.        |
| `reset_db`    | Wipes users/products/reviews and re-seeds categories. |

### Environment variables

| Variable           | Purpose                                             |
| ------------------ | --------------------------------------------------- |
| `MONGODB_URI`      | MongoDB connection string (required in production). |
| `MONGODB_DB_NAME`  | Database name (defaults to `amcho_pasro`).          |
| `FLASK_SECRET_KEY` | Session secret; random value generated if omitted.  |

All existing SQLite data is deprecated—new data must be inserted into MongoDB.
