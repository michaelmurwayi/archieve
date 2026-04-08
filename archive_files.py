import argparse
import configparser
import grp 
import logging 
import os
import pwd
import shutil
import sys
from datetime import datetime
from pathlib import Path

# database imports 
import psycopg2
from psycopg2 import OperationalError, InterfaceError, DatabaseError


# ----------------------------
# Configuration defaults
# ----------------------------

DEFAULT_CONFIG_FILES = [
    "/app/archiver.ini",            
    "/etc/archiver.ini",
    str(Path.home() / ".archiver.ini"),
]

DEFAULT_DB = {
    "host": "postgres",
    "port": "5432",
    "name": "archivedb",
    "user": "archiveuser",
    "password": "archivepass",
}

DEFAULT_ARCHIVE_DIR = "/archive"


def setup_logging():
    # create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # set up logging configuration
    logging.basicConfig(
        filename=log_dir / f"archive_files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )   

def parse_args():
    parser = argparse.ArgumentParser(description="Archive files from a specified directory.")
    parser.add_argument(
        "-g", "--group", 
        required=True, 
        help="Unix group name to archieve."
    )
    return parser.parse_args()

def resolve_archive_dir(config):
    """
    Check for archive directory in the following order:
        1. Environment variable ARCHIVER_ARCHIVE_DIR
        2. Configuration file under [archiver] section with key archive_dir
        3. Default value defined in the script (DEFAULT_ARCHIVE_DIR)
    """
    env_dir = os.environ.get("ARCHIVER_ARCHIVE_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    if config.has_section("archiver") and config.has_option("archiver", "archive_dir"):
        return Path(config.get("archiver", "archive_dir")).expanduser().resolve()

    return Path(DEFAULT_ARCHIVE_DIR).resolve()

def load_config():
    config = configparser.ConfigParser()
    existing = [p for p in DEFAULT_CONFIG_FILES if os.path.exists(p)]
    if existing:
        config.read(existing)
        logging.info("Loaded config from: %s", ", ".join(existing))
    return config

def resolve_db_config(config):
    """
    Priority:
    1. Environment variables (ARCHIVER_DB_HOST, ARCHIVER_DB_PORT, etc.)
    2. Configuration file under [database] section
    3. Default values defined in the script (DEFAULT_DB)
    """
    db = {}

    db["host"] = os.environ.get(
        "ARCHIVER_DB_HOST",
        config.get("database", "host", fallback=DEFAULT_DB["host"])
    )
    db["port"] = os.environ.get(
        "ARCHIVER_DB_PORT",
        config.get("database", "port", fallback=DEFAULT_DB["port"])
    )
    db["name"] = os.environ.get(
        "ARCHIVER_DB_NAME",
        config.get("database", "name", fallback=DEFAULT_DB["name"])
    )
    db["user"] = os.environ.get(
        "ARCHIVER_DB_USER",
        config.get("database", "user", fallback=DEFAULT_DB["user"])
    )
    db["password"] = os.environ.get(
        "ARCHIVER_DB_PASSWORD",
        config.get("database", "password", fallback=DEFAULT_DB["password"])
    )

    return db

class DBLogger:
    """
    If DB connection fails, archiving still continues.
    If DB fails mid-run, DB logging is disabled and archiving continues.
    """

    def __init__(self, db_config):
        self.db_config = db_config
        self.conn = None
        self.enabled = False

    def connect(self):
        try:
            self.conn = psycopg2.connect(
                host=self.db_config["host"],
                port=self.db_config["port"],
                dbname=self.db_config["name"],
                user=self.db_config["user"],
                password=self.db_config["password"],
            )
            self.conn.autocommit = True
            self.enabled = True
            logging.info("Connected to PostgreSQL at %s:%s",
                         self.db_config["host"], self.db_config["port"])
            self.ensure_table()
        except Exception as e:
            self.enabled = False
            self.conn = None
            logging.warning("Database unavailable; continuing without DB logging: %s", e)

    def ensure_table(self):
        if not self.enabled or not self.conn:
            return

        sql = """
        CREATE TABLE IF NOT EXISTS archived_files (
            id SERIAL PRIMARY KEY,
            group_name VARCHAR(100) NOT NULL,
            username VARCHAR(100) NOT NULL,
            source_path TEXT NOT NULL,
            archive_path TEXT NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_message TEXT,
            archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
        self._execute(sql)

    def log_event(self, group_name, username, source_path, archive_path, status, error_message=None):
        if not self.enabled or not self.conn:
            return

        sql = """
        INSERT INTO archived_files
            (group_name, username, source_path, archive_path, status, error_message, archived_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s);
        """
        params = (
            group_name,
            username,
            str(source_path),
            str(archive_path),
            status,
            error_message,
            datetime.utcnow(),
        )
        self._execute(sql, params)

    def _execute(self, sql, params=None):
        if not self.enabled or not self.conn:
            return

        try:
            with self.conn.cursor() as cur:
                cur.execute(sql, params)
        except (OperationalError, InterfaceError, DatabaseError, Exception) as e:
            logging.warning("Database logging failed; disabling DB logging for remainder of run: %s", e)
            self.disable()

    def disable(self):
        self.enabled = False
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.conn = None

    def close(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.conn = None
        self.enabled = False

def get_group_members(group_name):
    # Get members of a Unix group, including those with the group as their primary GID.
    try:
        group_info = grp.getgrnam(group_name)
    except KeyError:
        raise ValueError(f"Group '{group_name}' not found on the system")

    members = set(group_info.gr_mem)
    target_gid = group_info.gr_gid

    for user in pwd.getpwall():
        if user.pw_gid == target_gid:
            members.add(user.pw_name)

    return sorted(members)

def get_user_home(username):
    try:
        user_info = pwd.getpwnam(username)
        return Path(user_info.pw_dir).resolve()
    except KeyError:
        raise ValueError(f"User '{username}' not found in passwd database")


#  Helper functions for archiving logic
def is_hidden(path, root):
    try:
        rel = path.relative_to(root)
        return any(part.startswith(".") for part in rel.parts)
    except ValueError:
        return False


def destination_already_exists(dest):
    return dest.exists()


def move_file(src, dest):
    """
    Safe move across filesystems.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def archive_user_files(group_name, username, home_dir, archive_root, db_logger):
    """
    Preserve structure relative to home_dir:
    /home/alice/.bashrc -> /archive/alice/.bashrc
    /home/alice/docs/a.txt -> /archive/alice/docs/a.txt

    Edge cases handled:
    - missing home dir -> skip user
    - unreadable file -> log and continue
    - destination exists -> skip (safe re-run behavior)
    - DB failure -> archiving continues
    """
    moved = 0
    skipped = 0
    errors = 0

    if not home_dir.exists() or not home_dir.is_dir():
        msg = f"[{username}] Home directory missing or invalid: {home_dir}"
        logging.warning(msg)
        db_logger.log_event(group_name, username, home_dir, "", "failed", msg)
        return moved, skipped, errors + 1

    user_archive_root = archive_root / username

    logging.info("[%s] Archiving from %s to %s", username, home_dir, user_archive_root)

    for root, dirs, files in os.walk(home_dir, topdown=True):
        root_path = Path(root)

        # Prevent recursion if archive_root is inside the home dir
        filtered_dirs = []
        for d in dirs:
            candidate = (root_path / d).resolve()
            try:
                candidate.relative_to(archive_root.resolve())
                continue  # skip dirs inside archive
            except ValueError:
                filtered_dirs.append(d)
        dirs[:] = filtered_dirs

        # Create directories in archive path
        for d in dirs:
            dest_dir = user_archive_root / Path(root_path.relative_to(home_dir)) / d
            dest_dir.mkdir(parents=True, exist_ok=True)

        # Archive all files (including hidden)
        for filename in files:
            src = root_path / filename
            try:
                rel_path = src.relative_to(home_dir)
                dest = user_archive_root / rel_path

                # Edge case: already archived / second run
                if destination_already_exists(dest):
                    msg = f"Already archived, skipping existing destination: {dest}"
                    logging.info("[%s] %s", username, msg)
                    db_logger.log_event(group_name, username, src, dest, "skipped", msg)
                    skipped += 1
                    continue

                # Attempt move
                move_file(src, dest)
                logging.info("[%s] Archived: %s -> %s", username, src, dest)
                db_logger.log_event(group_name, username, src, dest, "success", None)
                moved += 1

            except PermissionError as e:
                msg = f"Permission denied: {src} ({e})"
                logging.error("[%s] %s", username, msg)
                db_logger.log_event(group_name, username, src, "", "failed", msg)
                errors += 1
                continue

            except OSError as e:
                msg = f"OS error while archiving {src}: {e}"
                logging.error("[%s] %s", username, msg)
                db_logger.log_event(group_name, username, src, "", "failed", msg)
                errors += 1
                continue

            except Exception as e:
                msg = f"Unexpected error while archiving {src}: {e}"
                logging.error("[%s] %s", username, msg)
                db_logger.log_event(group_name, username, src, "", "failed", msg)
                errors += 1
                continue

    return moved, skipped, errors


def main():
    # set up logging 
    setup_logging()
    args = parse_args()

    # load configurations
    config = load_config()

     # Resolve archive dir
    try:
        archive_root = resolve_archive_dir(config)
        archive_root.mkdir(parents=True, exist_ok=True)
        logging.info("Using archive directory: %s", archive_root)
    except Exception as e:
        logging.error("Failed to initialize archive directory: %s", e)
        return 2
    
    # Init DB logger
    db_config = resolve_db_config(config)
    db_logger = DBLogger(db_config)
    db_logger.connect()

    try:
        members = get_group_members(args.group)
    except ValueError as e:
        logging.error(str(e))
        db_logger.close()
        return 2

    logging.info("Archiving files for group '%s' with members: %s", args.group, ", ".join(members))

    # Edge case: group exists but no members
    if not members:
        logging.warning("Group '%s' exists but has no members", args.group)
        print(f"Group '{args.group}' exists but has no members to archive.")
        db_logger.close()
        return 0
    print(f"Archiving files for group '{args.group}' with members: {', '.join(members)}")
    logging.info("Resolved group '%s' members: %s", args.group, ", ".join(members))
    total_moved = 0
    total_skipped = 0
    total_errors = 0

      # Process each member independently
    for username in members:
        try:
            home_dir = get_user_home(username)
        except ValueError as e:
            logging.warning("[%s] %s", username, e)
            db_logger.log_event(args.group, username, "", "", "failed", str(e))
            total_errors += 1
            continue

        moved, skipped, errors = archive_user_files(
            group_name=args.group,
            username=username,
            home_dir=home_dir,
            archive_root=archive_root,
            db_logger=db_logger,
        )

        total_moved += moved
        total_skipped += skipped
        total_errors += errors

    logging.info(
        "Completed group '%s' | moved=%d | skipped=%d | errors=%d",
        args.group,
        total_moved,
        total_skipped,
        total_errors,
    )

    db_logger.close()

    # Exit code 0 for success, 1 for partial success (some files moved, some skipped/errors), 2 for critical failure (e.g. group not found)
    return 1 if total_errors > 0 else 0


if __name__ == "__main__":

    sys.exit(main())