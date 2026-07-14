from __future__ import annotations

import base64
import secrets


def main() -> None:
    print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"))


if __name__ == "__main__":
    main()
