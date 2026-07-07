from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Write local MySQL credentials to config.local.json.")
    parser.add_argument("--source", default=str(ROOT / "config.local.json"))
    parser.add_argument("--fallback", default=str(ROOT / "config.sample.json"))
    parser.add_argument("--out", default=str(ROOT / "config.local.json"))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        source = Path(args.fallback)

    with source.open("r", encoding="utf-8") as fh:
        config = json.load(fh)

    mysql = config.setdefault("storage", {}).setdefault("mysql", {})
    current_user = mysql.get("user")
    if not current_user or current_user == "YOUR_MYSQL_USER":
        default_user = "root"
    else:
        default_user = current_user

    user = input(f"MySQL user [{default_user}]: ").strip() or default_user
    password = getpass.getpass("MySQL password: ")
    if not password:
        raise SystemExit("Password cannot be empty.")

    config["storage"]["driver"] = "mysql"
    mysql["host"] = mysql.get("host", "127.0.0.1")
    mysql["port"] = int(mysql.get("port", 3306))
    mysql["database"] = mysql.get("database", "dynamic_dual_grid")
    mysql["user"] = user
    mysql["password"] = password
    mysql["password_env"] = ""

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"Wrote {out}")
    print("Storage driver: mysql")
    print(f"MySQL user: {user}")
    print("Password: stored in ignored local config.")


if __name__ == "__main__":
    main()
