from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Switch config.local.json to MySQL storage.")
    parser.add_argument("--source", default=str(ROOT / "config.local.json"))
    parser.add_argument("--fallback", default=str(ROOT / "config" / "config.sample.json"))
    parser.add_argument("--out", default=str(ROOT / "config.local.json"))
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        source = Path(args.fallback)

    with source.open("r", encoding="utf-8") as fh:
        config = json.load(fh)

    config.setdefault("storage", {})
    config["storage"]["driver"] = "mysql"
    config["storage"].setdefault("mysql", {})
    config["storage"]["mysql"].setdefault("host", "127.0.0.1")
    config["storage"]["mysql"].setdefault("port", 3306)
    config["storage"]["mysql"].setdefault("database", "dynamic_dual_grid")
    config["storage"]["mysql"].setdefault("user", "root")
    config["storage"]["mysql"].setdefault("password_env", "DDG_MYSQL_PASSWORD")

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"Wrote {out}")
    print("Storage driver: mysql")
    if config["storage"]["mysql"].get("password") and config["storage"]["mysql"].get("password") != "YOUR_MYSQL_PASSWORD":
        print("Password source: config.local.json")
    else:
        print("Password source: DDG_MYSQL_PASSWORD or interactive setup")


if __name__ == "__main__":
    main()
