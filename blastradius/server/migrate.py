from blastradius.server.config import Settings
from blastradius.server.db import Database


def main() -> None:
    db = Database(Settings.from_env())
    try:
        db.migrate()
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
