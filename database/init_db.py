"""Create (or upgrade) the TrustGuard SQLite database.  Usage: python -m database.init_db"""
from config.settings import get_settings
from database.db import Database


def main() -> None:
    path = get_settings().path("db_path")
    Database(path)
    print(f"Database ready at {path}")


if __name__ == "__main__":
    main()
