#!/usr/bin/env python3
"""接收一条 QQ 机器人单聊消息，获取并保存发送者的 user_openid。

使用方法：
    .venv/bin/pip install qq-botpy
    .venv/bin/python get_qq_openid.py

脚本优先从项目根目录的 secrets.env 读取 QQ_APP_ID 和
QQ_CLIENT_SECRET；缺少时会交互询问。收到第一条单聊消息后，脚本会将
QQ_RECIPIENT_OPENID 写入 secrets.env，然后自动退出。
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path

try:
    import botpy
    from botpy.message import C2CMessage
except ModuleNotFoundError as exc:
    if exc.name == "botpy":
        raise SystemExit(
            "缺少 QQ 官方 SDK，请先运行：\n"
            "  .venv/bin/pip install qq-botpy"
        ) from exc
    raise


def load_env_file(path: Path) -> None:
    """读取简单的 KEY=VALUE 文件，且不覆盖已有环境变量。"""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def update_env_file(path: Path, name: str, value: str) -> None:
    """更新或追加一个环境变量，并尽量保留文件的原有内容。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    replacement = f"{name}={value}"
    updated = False

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _ = stripped.split("=", 1)
        if key.strip() == name:
            lines[index] = replacement
            updated = True
            break

    if not updated:
        if lines and lines[-1]:
            lines.append("")
        lines.append(replacement)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


class OpenIDClient(botpy.Client):
    def __init__(self, *, env_file: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.env_file = env_file

    async def on_c2c_message_create(self, message: C2CMessage) -> None:
        openid = message.author.user_openid
        update_env_file(self.env_file, "QQ_RECIPIENT_OPENID", openid)

        print("\n" + "=" * 64)
        print("收到 QQ 单聊消息")
        print(f"消息内容：{message.content}")
        print(f"QQ_RECIPIENT_OPENID={openid}")
        print(f"已自动写入：{self.env_file}")
        print("=" * 64, flush=True)

        await self.close()


def get_credential(name: str, prompt: str, *, secret: bool = False) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value

    reader = getpass.getpass if secret else input
    value = reader(prompt).strip()
    if not value:
        raise SystemExit(f"{name} 不能为空。")
    return value


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    env_file = project_dir / "secrets.env"
    load_env_file(env_file)

    appid = get_credential("QQ_APP_ID", "请输入 QQ_APP_ID：")
    secret = get_credential(
        "QQ_CLIENT_SECRET",
        "请输入 QQ_CLIENT_SECRET（输入内容不会显示）：",
        secret=True,
    )
    update_env_file(env_file, "QQ_APP_ID", appid)
    update_env_file(env_file, "QQ_CLIENT_SECRET", secret)

    print("正在连接 QQ 机器人事件网关……")
    print("请用需要接收价格提醒的 QQ 给机器人发送一条单聊消息。")
    print("收到消息后会自动保存 QQ_RECIPIENT_OPENID 并退出；按 Control+C 可取消。")

    intents = botpy.Intents(public_messages=True)
    client = OpenIDClient(intents=intents, env_file=env_file)
    client.run(appid=appid, secret=secret)


if __name__ == "__main__":
    main()
