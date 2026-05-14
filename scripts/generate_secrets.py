#!/usr/bin/env python3
"""生成邀请码和管理员密码，写入 .env 文件。"""
import argparse
import secrets
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _read_env() -> str:
    if ENV_PATH.exists():
        return ENV_PATH.read_text(encoding="utf-8")
    return ""


def _write_env(text: str) -> None:
    ENV_PATH.write_text(text, encoding="utf-8")


def generate_invite_code():
    code = f"sga-{secrets.token_urlsafe(8)}"
    print(f"新邀请码: {code}")

    env_text = _read_env()
    updated = False
    lines = env_text.splitlines() if env_text.strip() else []

    new_lines = []
    for line in lines:
        if line.startswith("INVITE_CODES="):
            existing = line.split("=", 1)[1] if "=" in line else ""
            if existing:
                new_lines.append(f"INVITE_CODES={existing},{code}")
            else:
                new_lines.append(f"INVITE_CODES={code}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"INVITE_CODES={code}")

    _write_env("\n".join(new_lines) + "\n")
    return code


def generate_admin_password():
    password = secrets.token_urlsafe(12)
    print(f"新管理员密码: {password}")

    env_text = _read_env()
    lines = env_text.splitlines() if env_text.strip() else []

    new_lines = []
    updated = False
    for line in lines:
        if line.startswith("ADMIN_PASSWORD="):
            new_lines.append(f"ADMIN_PASSWORD={password}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"ADMIN_PASSWORD={password}")

    _write_env("\n".join(new_lines) + "\n")
    return password


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成凭据")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--invite", action="store_true", help="生成邀请码")
    group.add_argument("--admin", action="store_true", help="生成管理员密码")
    args = parser.parse_args()

    if args.invite:
        generate_invite_code()
    elif args.admin:
        generate_admin_password()
