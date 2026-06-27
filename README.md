# 元宝 Bot - Android 客户端

基于 Kivy 的 Android 原生 GUI 客户端，用于连接元宝 Bot 微信机器人。

## 功能

- WebSocket 实时连接，自动重连
- 群消息收发（文本、图片、贴纸、文件）
- 引用回复、艾特消息
- LaTeX `\scalebox` 放大文本
- 自动回复（支持自定义文本）
- 60 个猫猫头贴纸快捷发送
- 群成员列表查询
- GitHub Actions 自动构建 APK

## 快速开始

### 从源码运行（开发）

```bash
pip install -r requirements.txt
python main.py
```

### 构建 APK

使用 GitHub Actions（推荐）或本地 Buildozer：

```bash
buildozer android debug
```

APK 位于 `bin/` 目录。

## 配置文件

首次启动会弹出配置界面，或手动创建 `config.json`：

```json
{
    "bot_id": "your_bot_id",
    "group_code": "your_group_code",
    "sign_token_url": ""
}
```

## 项目结构

```
├── main.py              # Kivy 应用入口
├── buildozer.spec       # Buildozer 构建配置
├── requirements.txt     # Python 依赖
├── src/
│   ├── bot_client.py    # Bot 客户端核心（WebSocket、命令、消息）
│   └── protocol.py      # Protobuf 协议编解码
└── .github/workflows/   # GitHub Actions CI
```

## 协议

MIT
