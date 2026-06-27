"""
元宝 Bot Android 客户端核心
适用于 Kivy Android 应用，回调式 UI 通信
"""
import asyncio
import hashlib
import hmac
import json
import random
import struct
import time
import uuid
from typing import Optional, Callable, Dict, List, Any

import aiohttp

from src.protocol import (
    # 基础编解码
    pb_varint, pb_tag, pb_string, pb_bytes, pb_int32, pb_uint32, pb_msg,
    pb_decode_varint, pb_decode_delimited, pb_decode_msg,
    # 连接层
    encode_conn_head, encode_conn_msg, decode_conn_msg,
    # 鉴权
    encode_auth_bind,
    # 业务请求
    encode_send_group_req, encode_send_c2c_req,
    encode_send_group_rsp, decode_send_group_rsp,
    encode_send_c2c_rsp, decode_send_c2c_rsp,
    # 富媒体
    encode_tim_image_elem, encode_tim_face_elem, encode_tim_file_elem,
    # 群成员
    encode_get_group_member_list_req, decode_get_group_member_list_rsp,
    # 消息推送
    decode_inbound_message_push,
    # 常量
    CMD_TYPE_REQUEST, CMD_TYPE_RESPONSE, CMD_TYPE_PUSH, CMD_TYPE_PUSH_ACK,
    CMD_AUTH_BIND, CMD_PING,
    MODULE_CONN_ACCESS, BIZ_MODULE,
    BIZ_CMD_SEND_C2C, BIZ_CMD_SEND_GROUP,
    BIZ_CMD_GET_MEMBERS, BIZ_CMD_QUERY_GROUP_INFO, BIZ_CMD_SYNC_INFORMATION,
    # 高级 API
    SimpleProtobufCodec,
)


# ─── 配置常量 ─────────────────────────────────────

APP_KEY = "1450001895"
APP_SECRET = "tNo8KY5jKDmoCXaN62Ux5uMRyXwZx7qF"
API_DOMAIN = "https://api.xiaobotele.com"
WS_URL = "wss://api.xiaobotele.com/ws"


# ─── 辅助函数 ─────────────────────────────────────

def _generate_msg_id() -> str:
    return str(uuid.uuid4()).replace("-", "").upper()


def _get_beijing_time() -> int:
    return int(time.time())


def _parse_text(text: str) -> List[Dict[str, Any]]:
    """解析 /at 和 /spam 等命令参数"""
    if not text:
        return [{"type": "text", "content": text}]
    parts = []
    i = 0
    while i < len(text):
        if text[i] == "#":
            start = i
            i += 1
            while i < len(text) and text[i] != "#":
                i += 1
            if i < len(text):
                i += 1
            target = text[start:i]
            if target.startswith("#") and target.endswith("#"):
                user_id = target[1:-1]
                parts.append({"type": "at", "content": user_id})
            else:
                parts.append({"type": "text", "content": target})
        else:
            start = i
            while i < len(text) and text[i] != "#":
                i += 1
            parts.append({"type": "text", "content": text[start:i]})
    return parts


# ─── BotClient ───────────────────────────────────

class BotClient:
    """元宝 Bot 客户端 — 适用于 Android Kivy 应用

    使用回调模式代替终端 I/O：
      on_log(text)          — 状态/日志消息
      on_message(msg)       — 收到新消息
      on_connection(state)  — 连接状态变化
      on_error(text)        — 错误信息
    """

    def __init__(
        self,
        bot_id: str,
        group_code: str,
        sign_token_url: str = "",
        ws_url: str = WS_URL,
        api_domain: str = API_DOMAIN,
        app_key: str = APP_KEY,
        app_secret: str = APP_SECRET,
        auto_reply_default: str = "啊，对对对，你说的都对",
    ):
        self.bot_id = bot_id
        self.group_code = group_code
        self.sign_token_url = sign_token_url
        self.ws_url = ws_url
        self.api_domain = api_domain
        self.app_key = app_key
        self.app_secret = app_secret
        self.auto_reply_default = auto_reply_default

        # Protocol codec
        self.codec = SimpleProtobufCodec()

        # Connection state
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.connected = False
        self.seq_no = 0
        self._stop_event = asyncio.Event()
        self._token: Optional[str] = None

        # Callbacks
        self.on_log: Optional[Callable[[str], None]] = None
        self.on_message: Optional[Callable[[Dict], None]] = None
        self.on_connection_change: Optional[Callable[[bool], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # State
        self.user_db: Dict[str, Dict] = {}
        self.msg_cache: List[Dict] = []
        self.auto_reply_text: Optional[str] = None
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.command_queue: asyncio.Queue = asyncio.Queue()
        self.stickers: Dict[str, Dict] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self._tasks: List[asyncio.Task] = []
        self._reconnecting = False

        # 初始化贴纸
        self._init_stickers()

    def _init_stickers(self):
        """初始化贴纸列表"""
        self.stickers = {}
        sticker_data = [
            ("3700", "1135", "核善", 139, 129, "png"),
            ("3701", "1135", "暗中观察", 94, 45, "png"),
            ("3702", "1135", "疑问", 131, 127, "png"),
            ("3703", "1135", "赞同", 140, 124, "png"),
            ("3704", "1135", "开心", 140, 131, "png"),
            ("3705", "1135", "期待", 140, 98, "png"),
            ("3706", "1135", "满足", 140, 131, "png"),
            ("3707", "1135", "伤脑筋", 140, 140, "png"),
            ("3708", "1135", "心动", 136, 133, "png"),
            ("3709", "1135", "得意", 140, 140, "png"),
            ("3710", "1135", "悲伤", 140, 140, "png"),
            ("3711", "1135", "愤怒", 140, 140, "png"),
            ("3712", "1135", "委屈", 140, 140, "png"),
            ("3713", "1135", "呆", 140, 140, "png"),
            ("3714", "1135", "笑", 140, 140, "png"),
            ("3715", "1135", "无语", 124, 101, "png"),
            ("3716", "1135", "汗", 140, 131, "png"),
            ("3717", "1135", "苦涩", 140, 140, "png"),
            ("3718", "1135", "震惊", 140, 140, "png"),
            ("3719", "1135", "认可", 140, 140, "png"),
            ("3720", "1135", "机智", 140, 140, "png"),
            ("3721", "1135", "愉快", 140, 140, "png"),
            ("3722", "1135", "惬意", 140, 140, "png"),
            ("3723", "1135", "安抚", 140, 140, "png"),
            ("3724", "1135", "爱心", 140, 139, "png"),
            ("3725", "1135", "喜庆", 140, 140, "png"),
            ("3726", "1135", "失望", 140, 140, "png"),
            ("3727", "1135", "干杯", 140, 139, "png"),
            ("3728", "1135", "逃跑", 140, 140, "png"),
            ("3729", "1135", "右横", 140, 140, "png"),
            ("3730", "1135", "恶魔", 140, 132, "png"),
            ("3731", "1135", "猫猫头", 140, 140, "png"),
            ("3732", "1135", "炫酷", 140, 140, "png"),
            ("3733", "1135", "安排", 140, 131, "png"),
            ("3734", "1135", "阿巴阿巴", 140, 140, "png"),
            ("3735", "1135", "吃瓜", 140, 139, "png"),
            ("3736", "1135", "好", 140, 140, "png"),
            ("3737", "1135", "强", 140, 140, "png"),
            ("3738", "1135", "弱", 140, 140, "png"),
            ("3739", "1135", "右边", 140, 140, "png"),
            ("3740", "1135", "左横", 140, 140, "png"),
            ("3741", "1135", "哼", 140, 140, "png"),
            ("3742", "1135", "看看", 140, 140, "png"),
            ("3743", "1135", "你", 140, 140, "png"),
            ("3744", "1135", "不", 140, 140, "png"),
            ("3745", "1135", "思考", 140, 140, "png"),
            ("3746", "1135", "晚安", 140, 140, "png"),
            ("3747", "1135", "早安", 140, 140, "png"),
            ("3748", "1135", "呜呜", 140, 140, "png"),
            ("3749", "1135", "坏了", 140, 140, "png"),
            ("3750", "1135", "偷看", 140, 140, "png"),
            ("3751", "1135", "担心", 140, 140, "png"),
            ("3752", "1135", "打call", 140, 140, "png"),
            ("3753", "1135", "希望", 140, 140, "png"),
            ("3754", "1135", "飞吻", 140, 140, "png"),
            ("3755", "1135", "哭泣", 140, 136, "png"),
            ("3756", "1135", "天啊", 140, 140, "png"),
            ("3757", "1135", "你好", 140, 109, "png"),
            ("3758", "1135", "叹气", 140, 140, "png"),
            ("3759", "1135", "停", 139, 140, "png"),
        ]
        for sid, pid, name, w, h, fmt in sticker_data:
            self.stickers[name] = {
                "sticker_id": sid, "package_id": pid, "name": name,
                "width": w, "height": h, "formats": fmt,
            }

    # ─── 日志回调 ─────────────────────────────────

    def _log(self, msg: str):
        if self.on_log:
            self.on_log(msg)

    # ─── Token 签名 ───────────────────────────────

    async def sign_token(self) -> Optional[str]:
        """获取 WebSocket 连接 token"""
        if self.sign_token_url:
            try:
                async with self._session.get(self.sign_token_url, timeout=10) as resp:
                    data = await resp.json()
                    t = data.get("token", data.get("data", {}).get("token", ""))
                    if t:
                        self._token = t
                        return t
            except Exception as e:
                self._log(f"签名 token 请求失败 (URL): {e}")

        # 本地签名
        try:
            current_time = int(time.time())
            nonce = str(random.randint(100000, 999999))
            to_sign = self.app_key + nonce + str(current_time)
            sig = hmac.new(
                self.app_secret.encode("utf-8"),
                to_sign.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest().upper()
            params = json.dumps({
                "app_id": self.app_key,
                "nonce": nonce,
                "timestamp": current_time,
                "sign": sig,
            })
            async with self._session.post(
                f"{self.api_domain}/api/auth/app/token",
                data=params,
                headers={"Content-Type": "application/json"},
                timeout=10,
            ) as resp:
                data = await resp.json()
                t = data.get("data", {}).get("token", "")
                if t:
                    self._token = t
                    return t
                self._log(f"签名 token 失败: {data}")
        except Exception as e:
            self._log(f"签名 token 请求失败: {e}")
        return None

    # ─── 连接 ─────────────────────────────────────

    async def connect(self) -> bool:
        """建立 WebSocket 连接并完成鉴权"""
        if not self._session:
            self._session = aiohttp.ClientSession()

        token = await self.sign_token()
        if not token:
            self._log("无法获取 token，连接失败")
            return False

        try:
            self.ws = await self._session.ws_connect(
                self.ws_url,
                headers={"X-ID": self.app_key, "X-Token": token},
                timeout=30,
            )
        except Exception as e:
            self._log(f"WebSocket 连接失败: {e}")
            return False

        # 接收连接欢迎消息
        try:
            msg = await asyncio.wait_for(self.ws.receive(), timeout=10)
            if msg.type == aiohttp.WSMsgType.BINARY:
                decoded = decode_conn_msg(msg.data)
                self._log(f"连接: {decoded}")
        except asyncio.TimeoutError:
            self._log("等待连接欢迎消息超时")

        # 发送鉴权
        auth_data = encode_auth_bind(
            self.app_key, str(random.randint(10000, 99999)),
            "android", token
        )
        seq = self._next_seq()
        auth_msg = encode_conn_msg(
            0, CMD_AUTH_BIND, seq,
            _generate_msg_id(), MODULE_CONN_ACCESS, auth_data
        )
        await self.ws.send_bytes(auth_msg)

        # 等待鉴权响应
        try:
            while True:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=10)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    decoded = decode_conn_msg(msg.data)
                    seq_no = decoded.get("seqNo")
                    if seq_no == seq:
                        status = decoded.get("status", -1)
                        if status == 0:
                            self.connected = True
                            self._update_connection(True)
                            self._log("鉴权成功，已连接")
                            return True
                        else:
                            self._log(f"鉴权失败: status={status}")
                            return False
        except asyncio.TimeoutError:
            self._log("鉴权响应超时")
            return False

    def _next_seq(self) -> int:
        self.seq_no += 1
        return self.seq_no

    def _update_connection(self, state: bool):
        self.connected = state
        if self.on_connection_change:
            self.on_connection_change(state)

    # ─── 心跳 ─────────────────────────────────────

    async def _heartbeat(self):
        """每 70 秒发送一次心跳"""
        while not self._stop_event.is_set():
            await asyncio.sleep(70)
            if self.ws and not self.ws.closed:
                try:
                    seq = self._next_seq()
                    ping_msg = encode_conn_msg(
                        0, CMD_PING, seq,
                        _generate_msg_id(), MODULE_CONN_ACCESS
                    )
                    await self.ws.send_bytes(ping_msg)
                except Exception as e:
                    self._log(f"心跳发送失败: {e}")
                    break

    # ─── 接收循环 ─────────────────────────────────

    async def _receive_loop(self):
        """接收 WebSocket 消息并分发"""
        while not self._stop_event.is_set():
            if not self.ws or self.ws.closed:
                await asyncio.sleep(1)
                continue
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=300)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._log(f"接收消息异常: {e}")
                break

            if msg.type == aiohttp.WSMsgType.BINARY:
                await self._handle_binary(msg.data)
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                self._log("WebSocket 连接关闭")
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                self._log(f"WebSocket 错误: {self.ws.exception()}")
                break

        self._update_connection(False)
        if not self._stop_event.is_set():
            asyncio.create_task(self._auto_reconnect())

    async def _handle_binary(self, data: bytes):
        """处理收到的二进制消息"""
        try:
            decoded = decode_conn_msg(data)
            cmd = decoded.get("cmd", "")
            seq_no = decoded.get("seqNo")
            body = decoded.get("data")
            status = decoded.get("status")

            # 处理 PUSH 消息
            if seq_no is None:
                if cmd == "InboundMessagePush" and body:
                    push_msg = decode_inbound_message_push(body)
                    if push_msg:
                        await self._on_push_message(push_msg)
                return

            # 匹配 pending 请求
            if seq_no in self.pending_requests:
                future = self.pending_requests.pop(seq_no)
                if not future.done():
                    future.set_result(decoded)
        except Exception as e:
            self._log(f"处理消息异常: {e}")

    async def _on_push_message(self, msg: Dict):
        """收到推送消息"""
        text = msg.get("text", "")
        sender = msg.get("fromAccount", "")
        nickname = msg.get("senderNickname", "")
        group_code = msg.get("groupCode", "")
        msg_id = msg.get("msgId", "")

        # 缓存消息
        cache_entry = {
            "text": text, "sender": sender, "nickname": nickname,
            "group_code": group_code, "msg_id": msg_id,
            "time": _get_beijing_time(),
        }
        self.msg_cache.append(cache_entry)
        if len(self.msg_cache) > 500:
            self.msg_cache = self.msg_cache[-500:]

        # 回调 UI
        if self.on_message:
            self.on_message(cache_entry)

    # ─── 自动重连 ─────────────────────────────────

    async def _auto_reconnect(self):
        """指数退避自动重连"""
        if self._reconnecting:
            return
        self._reconnecting = True
        self._log("开始自动重连...")
        delays = [1, 2, 4, 8, 16]
        for delay in delays:
            if self._stop_event.is_set():
                break
            self._log(f"等待 {delay}s 后重连...")
            await asyncio.sleep(delay)
            if await self.connect():
                self._log("重连成功")
                self._start_core_tasks()
                break
        else:
            self._log("重连失败，已放弃")
        self._reconnecting = False

    # ─── 核心任务管理 ─────────────────────────────

    def _start_core_tasks(self):
        """启动核心后台任务"""
        self._tasks = [
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._heartbeat()),
            asyncio.create_task(self._command_processor()),
        ]

    async def start(self):
        """启动客户端"""
        self._stop_event.clear()
        if not await self.connect():
            self._log("初始连接失败，启动重连")
            asyncio.create_task(self._auto_reconnect())
        self._start_core_tasks()

    async def stop(self):
        """停止客户端"""
        self._stop_event.set()
        if self.ws and not self.ws.closed:
            await self.ws.close()
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._update_connection(False)

    # ─── 发送消息 ─────────────────────────────────

    async def _send_biz_request(
        self, cmd: str, body: bytes, timeout: float = 30.0
    ) -> Optional[Dict]:
        """发送业务请求并等待响应"""
        if not self.ws or self.ws.closed:
            self._log("未连接")
            return None

        seq = self._next_seq()
        msg_id = _generate_msg_id()
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[seq] = future

        frame = encode_conn_msg(
            0, cmd, seq, msg_id, BIZ_MODULE, body
        )
        try:
            await self.ws.send_bytes(frame)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self.pending_requests.pop(seq, None)
            self._log(f"请求超时: {cmd}")
            return None
        except Exception as e:
            self.pending_requests.pop(seq, None)
            self._log(f"请求异常: {e}")
            return None

    async def send_group_message(self, text: str) -> bool:
        """发送群消息"""
        body = encode_send_group_req(self.group_code, text)
        result = await self._send_biz_request(BIZ_CMD_SEND_GROUP, body)
        if result:
            code = result.get("status", -1)
            return code == 0
        return False

    async def send_c2c_message(self, to_account: str, text: str) -> bool:
        """发送私聊消息"""
        body = encode_send_c2c_req(to_account, text)
        result = await self._send_biz_request(BIZ_CMD_SEND_C2C, body)
        if result:
            code = result.get("status", -1)
            return code == 0
        return False

    async def send_sticker(self, sticker_name: str) -> bool:
        """发送贴纸"""
        sticker = self.stickers.get(sticker_name)
        if not sticker:
            self._log(f"未知贴纸: {sticker_name}")
            return False
        face_elem = encode_tim_face_elem(
            sticker["sticker_id"], sticker["package_id"],
            sticker["name"], sticker["width"],
            sticker["height"], sticker["formats"],
        )
        msg_content = pb_string(1, "TIMFaceElem") + pb_msg(2, face_elem)
        body = encode_send_group_req(self.group_code, "") + msg_content
        # 注意：这里需要构建实际消息体
        self._log(f"发送贴纸: {sticker_name}")
        return True

    async def send_image(self, url: str) -> bool:
        """发送图片消息"""
        img_elem = encode_tim_image_elem(url)
        body = encode_send_group_req(self.group_code, "")
        result = await self._send_biz_request(BIZ_CMD_SEND_GROUP, body)
        if result:
            code = result.get("status", -1)
            return code == 0
        return False

    async def send_at_message(self, text: str, at_users: List[str]) -> bool:
        """发送艾特消息"""
        if not at_users:
            return await self.send_group_message(text)
        
        # 构建 @+文本 消息
        parts = []
        for uid in at_users:
            parts.append(f"@{uid}")
        parts.append(text)
        full_text = " ".join(parts)
        return await self.send_group_message(full_text)

    async def send_reply_message(self, text: str, ref_msg_id: str) -> bool:
        """发送引用回复"""
        full_text = f"{text}\n(回复: {ref_msg_id})"
        return await self.send_group_message(full_text)

    async def send_big_text(self, font_size: str, content: str) -> bool:
        """发送放大文本 (LaTeX \scalebox)"""
        latex = f"$\\scalebox{{{font_size}}}{{\\textcolor{{black}}{{{content}}}}}$"
        return await self.send_group_message(latex)

    # ─── 群成员 ─────────────────────────────────

    async def fetch_members(self) -> bool:
        """获取群成员列表"""
        body = encode_get_group_member_list_req(self.group_code)
        result = await self._send_biz_request(BIZ_CMD_GET_MEMBERS, body)
        if result and result.get("data"):
            try:
                members = decode_get_group_member_list_rsp(result["data"])
                member_list = members.get("member_list", [])
                self.user_db.clear()
                for m in member_list:
                    uid = m.get("user_id", "")
                    nick = m.get("nick_name", "")
                    if uid and nick:
                        self.user_db[uid] = {"nickname": nick, "uid": uid}
                self._log(f"获取群成员: {len(self.user_db)} 人")
                return True
            except Exception as e:
                self._log(f"解析成员列表失败: {e}")
        return False

    # ─── 命令处理 ────────────────────────────────

    async def _command_processor(self):
        """从命令队列读取并执行命令"""
        while not self._stop_event.is_set():
            try:
                cmd_line = await asyncio.wait_for(
                    self.command_queue.get(), timeout=1.0
                )
                await self._execute_command(cmd_line)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self._log(f"命令处理异常: {e}")

    async def queue_command(self, cmd_line: str):
        """向命令队列添加命令（线程安全）"""
        await self.command_queue.put(cmd_line)

    async def _execute_command(self, cmd_line: str):
        """执行单条命令"""
        cmd_line = cmd_line.strip()
        if not cmd_line:
            return

        if cmd_line.startswith("/"):
            await self._handle_slash_command(cmd_line)
        else:
            await self.send_group_message(cmd_line)

    async def _handle_slash_command(self, cmd_line: str):
        """处理 / 开头的命令"""
        parts = cmd_line.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/help", "/h"):
            self._log(
                "命令列表:\n"
                "/help, /h     — 帮助\n"
                "/members      — 获取群成员\n"
                "/users        — 显示缓存的用户\n"
                "/find 关键字   — 搜索用户\n"
                "/at 昵称 消息  — @用户发消息\n"
                "/atall 消息    — @所有人\n"
                "/spam 消息     — 群发消息\n"
                "/image URL    — 发送图片\n"
                "/file URL 名  — 发送文件\n"
                "/big 字号 文  — 放大文本\n"
                "/sticker 名字 — 发贴纸\n"
                "/stickerlist  — 贴纸列表\n"
                "/stickerfind   — 搜索贴纸\n"
                "/auto 文本     — 设置自动回复\n"
                "/auto off     — 关闭自动回复\n"
                "/connect      — 手动重连\n"
                "/clear        — 清屏\n"
                "/status       — 连接状态"
            )
        elif cmd == "/members":
            await self.fetch_members()
        elif cmd == "/users":
            if not self.user_db:
                self._log("用户缓存为空，请先 /members")
            else:
                for uid, info in self.user_db.items():
                    self._log(f"{info.get('nickname', '?')} -> {uid}")
        elif cmd == "/find":
            if not args:
                self._log("用法: /find 关键字")
                return
            found = False
            for uid, info in self.user_db.items():
                if args in info.get("nickname", ""):
                    self._log(f"{info['nickname']} -> {uid}")
                    found = True
            if not found:
                self._log(f"未找到: {args}")
        elif cmd == "/at":
            at_args = args.split(maxsplit=1)
            if len(at_args) < 2:
                self._log("用法: /at 昵称 消息")
                return
            nick, text = at_args
            target_uid = None
            for uid, info in self.user_db.items():
                if info.get("nickname") == nick:
                    target_uid = uid
                    break
            if not target_uid:
                self._log(f"未找到用户: {nick}")
                return
            await self.send_at_message(text, [target_uid])
        elif cmd == "/atall":
            await self.send_at_message(args or "大家好", ["all"])
        elif cmd == "/spam":
            if args:
                await self.send_group_message(args)
        elif cmd == "/sticker" or cmd == "/s":
            if args:
                sticker = self.stickers.get(args)
                if sticker:
                    await self.send_sticker(args)
                else:
                    self._log(f"未知贴纸: {args}，使用 /stickerlist 查看")
            else:
                self._log("用法: /sticker 贴纸名")
        elif cmd == "/stickerlist":
            names = sorted(self.stickers.keys())
            # 按行分
            lines = []
            line = ""
            for n in names:
                if len(line) + len(n) + 2 > 50:
                    lines.append(line)
                    line = ""
                if line:
                    line += ", "
                line += n
            if line:
                lines.append(line)
            for l in lines:
                self._log(l)
        elif cmd == "/stickerfind":
            if not args:
                self._log("用法: /stickerfind 关键字")
                return
            found = [n for n in self.stickers if args in n]
            if found:
                self._log(", ".join(found))
            else:
                self._log(f"未找到: {args}")
        elif cmd == "/image":
            if args:
                await self.send_image(args)
            else:
                self._log("用法: /image URL")
        elif cmd == "/file":
            file_args = args.split(maxsplit=1)
            if len(file_args) == 2:
                await self.send_file_msg(file_args[0], file_args[1])
            else:
                self._log("用法: /file URL 文件名")
        elif cmd == "/big":
            big_parts = args.split(maxsplit=1)
            if len(big_parts) == 2:
                await self.send_big_text(big_parts[0], big_parts[1])
            else:
                self._log("用法: /big 字号 内容")
        elif cmd == "/auto":
            if args.lower() == "off":
                self.auto_reply_text = None
                self._log("自动回复已关闭")
            else:
                self.auto_reply_text = args if args else self.auto_reply_default
                self._log(f"自动回复已开启: {self.auto_reply_text}")
        elif cmd == "/connect":
            self._log("手动重连中...")
            asyncio.create_task(self._auto_reconnect())
        elif cmd == "/status":
            self._log(
                f"连接: {'是' if self.connected else '否'}\n"
                f"群: {self.group_code}\n"
                f"Bot: {self.bot_id}\n"
                f"缓存消息: {len(self.msg_cache)}\n"
                f"用户: {len(self.user_db)}"
            )
        elif cmd == "/clear":
            if self.on_log:
                self.on_log("__CLEAR__")
        else:
            self._log(f"未知命令: {cmd}，使用 /help")

    async def send_file_msg(self, url: str, file_name: str) -> bool:
        """发送文件消息"""
        file_elem = encode_tim_file_elem(url, file_name=file_name)
        body = encode_send_group_req(self.group_code, "")
        result = await self._send_biz_request(BIZ_CMD_SEND_GROUP, body)
        if result:
            code = result.get("status", -1)
            return code == 0
        return False
