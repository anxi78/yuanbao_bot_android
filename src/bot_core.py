"""
元宝 Bot 核心 - Android 适配版
基于 sender.py 提取，适配 Kivy event loop
"""
import asyncio
import hashlib
import hmac
import json
import logging
import random
import string
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Dict, List, Any

try:
    import requests
except ImportError:
    requests = None

try:
    import websockets
except ImportError:
    websockets = None

from . import protocol as proto

logger = logging.getLogger("BotCore")

# ─── 默认配置 ───
API_DOMAIN = "o-a0x9ax22n8k0k7n4p8o.apigateway.apiopen.top"
WS_URL = "wss://o-a0x9ax22n8k0k7n4p8o.apigateway.apiopen.top/api/v5/websocket"
API_VERSION = "1.0.0"


class BotConfig:
    """机器人配置"""
    def __init__(self, config: dict):
        self.api_domain: str = config.get("API_DOMAIN", API_DOMAIN)
        self.ws_url: str = config.get("WS_URL", WS_URL)
        self.app_key: str = config.get("APP_KEY", "")
        self.app_secret: str = config.get("APP_SECRET", "")
        self.default_group_code: str = config.get("DEFAULT_GROUP_CODE", "")
        self.bot_id: str = config.get("BOT_ID", "")
        self.auto_connect: bool = config.get("AUTO_CONNECT", True)


class BotClient:
    """
    异步 Bot 客户端
    适配 Android Kivy 的事件循环
    """

    def __init__(self, config: dict):
        self.config = BotConfig(config)
        self.token: Optional[str] = None
        self.bot_id: Optional[str] = None
        self.ws = None
        self.connected = False
        self.seq_no = 0
        self.group_code: str = self.config.default_group_code
        self.user_db: Dict[str, str] = {}
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.msg_cache: List[dict] = []
        self._reconnecting = False
        self._recv_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # 回调
        self.on_message: Optional[Callable] = None  # async callable(msg_dict)
        self.on_connection_state: Optional[Callable] = None  # callable(connected: bool)
        self.on_log: Optional[Callable] = None  # callable(text: str)

    def _log(self, text: str):
        logger.debug(text)
        if self.on_log:
            self.on_log(text)

    def _get_beijing_time(self) -> str:
        utc = datetime.now(timezone.utc)
        beijing = utc + timedelta(hours=8)
        return beijing.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    def _generate_msg_id(self) -> str:
        import uuid
        return uuid.uuid4().hex

    # ─── 连接 / 鉴权 ─────────────────────────────

    def sign_token(self) -> bool:
        """HMAC-SHA256 签名获取 token"""
        if not requests:
            self._log("requests 模块未安装")
            return False
        url = f"https://{self.config.api_domain}/api/v5/robotLogic/sign-token"
        nonce = ''.join(random.choices(string.hexdigits.lower(), k=32))
        timestamp = self._get_beijing_time()
        plain = f"{nonce}{timestamp}{self.config.app_key}{self.config.app_secret}"
        signature = hmac.new(
            self.config.app_secret.encode(),
            plain.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-AppVersion": "1.0.11",
            "X-OperationSystem": "android",
            "X-Instance-Id": str(random.randint(1, 9999)),
            "X-Bot-Version": "2026.6.27"
        }
        body = {
            "app_key": self.config.app_key,
            "nonce": nonce,
            "signature": signature,
            "timestamp": timestamp
        }
        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
            result = response.json()
            if result.get("code") == 0:
                data = result["data"]
                self.token = data["token"]
                self.bot_id = data["bot_id"]
                self._log(f"签票成功! Bot ID: {self.bot_id}")
                return True
            else:
                self._log(f"签票失败: {result}")
                return False
        except Exception as e:
            self._log(f"签票错误: {e}")
            return False

    async def connect(self) -> bool:
        """建立 WebSocket 连接 + 鉴权"""
        if not websockets:
            self._log("websockets 模块未安装")
            return False
        if not self.token and not self.sign_token():
            self._log("无法获取 token")
            return False
        try:
            self.ws = await websockets.connect(self.config.ws_url)
            auth_msg = self._build_auth_bind_msg()
            await self.ws.send(auth_msg)
            resp = await asyncio.wait_for(self.ws.recv(), timeout=10)
            self.connected = True
            self._log("WebSocket 连接成功!")

            # 发送命令同步
            try:
                sync_msg = self._build_sync_information_req()
                await self.ws.send(sync_msg)
            except Exception:
                pass

            if self.on_connection_state:
                self.on_connection_state(True)

            # 启动心跳和接收
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._recv_task = asyncio.create_task(self._receive_loop())
            return True
        except Exception as e:
            self._log(f"连接失败: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=1.0)
            except Exception:
                pass
            self.ws = None
        if self.on_connection_state:
            self.on_connection_state(False)
        self._log("已断开连接")

    # ─── 消息构建 ─────────────────────────────

    def _build_auth_bind_msg(self) -> bytes:
        auth_data = proto.encode_auth_bind(
            biz_id="ybBot",
            uid=self.bot_id or "",
            source="android",
            token=self.token or ""
        )
        msg_id = self._generate_msg_id()
        frame = proto.encode_conn_msg(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.CMD_AUTH_BIND,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=proto.MODULE_CONN_ACCESS,
            data=auth_data
        )
        self.seq_no += 1
        return frame

    def _build_sync_information_req(self) -> bytes:
        codec = proto.SimpleProtobufCodec()
        data = b""
        data += proto.pb_int32(1, 1)  # syncType
        data += codec.encode_string(2, API_VERSION)  # botVersion
        data += codec.encode_string(3, "1.0.0")  # pluginVersion
        sync_cmds = b""
        cmd_bytes = codec.encode_string(1, "/help")
        cmd_bytes += codec.encode_string(2, "显示帮助信息")
        sync_cmds += codec.encode_message_field(1, cmd_bytes)
        data += codec.encode_message_field(11, sync_cmds)

        head = codec.encode_head(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.BIZ_CMD_SYNC_INFORMATION,
            seq_no=self.seq_no,
            msg_id=self._generate_msg_id(),
            module=proto.BIZ_MODULE
        )
        self.seq_no += 1
        return codec.encode_conn_msg(head, data)

    def _build_group_msg(self, text: str, group_code: str = None) -> bytes:
        target = group_code or self.group_code
        codec = proto.SimpleProtobufCodec()
        msg_id = self._generate_msg_id()
        biz = codec.encode_send_group_msg_req(
            msg_id=msg_id,
            group_code=target,
            from_account=self.bot_id or "",
            text=text
        )
        head = codec.encode_head(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.BIZ_CMD_SEND_GROUP,
            seq_no=self.seq_no,
            msg_id=self._generate_msg_id(),
            module=proto.BIZ_MODULE
        )
        self.seq_no += 1
        return codec.encode_conn_msg(head, biz)

    def _build_dm_msg(self, to_account: str, text: str) -> bytes:
        codec = proto.SimpleProtobufCodec()
        biz = codec.encode_send_c2c_msg_req(
            msg_id=self._generate_msg_id(),
            to_account=to_account,
            from_account=self.bot_id or "",
            text=text
        )
        head = codec.encode_head(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.BIZ_CMD_SEND_C2C,
            seq_no=self.seq_no,
            msg_id=self._generate_msg_id(),
            module=proto.BIZ_MODULE
        )
        self.seq_no += 1
        return codec.encode_conn_msg(head, biz)

    def _build_get_members_msg(self) -> bytes:
        codec = proto.SimpleProtobufCodec()
        msg_id = self._generate_msg_id()
        biz = codec.encode_get_group_member_list_req(self.group_code or "")
        head = codec.encode_head(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.BIZ_CMD_GET_MEMBERS,
            seq_no=self.seq_no,
            msg_id=msg_id,
            module=proto.BIZ_MODULE
        )
        self.seq_no += 1
        return msg_id, codec.encode_conn_msg(head, biz)

    def _build_reply_msg(self, text: str, ref_msg_id: str,
                         at_user_id: str = "", at_nickname: str = "",
                         target_group: str = None) -> bytes:
        """构建带引用+可选的艾特的群消息"""
        gc = target_group or self.group_code
        codec = proto.SimpleProtobufCodec()
        msg_id = self._generate_msg_id()

        if at_user_id:
            # 引用+艾特
            display_name = at_nickname or at_user_id
            at_data = json.dumps({
                "elem_type": 1002,
                "text": f"@{display_name}",
                "user_id": at_user_id
            })
            at_content = codec.encode_string(4, at_data)
            at_elem = b''
            at_elem += codec.encode_string(1, "TIMCustomElem")
            at_elem += codec.encode_message_field(2, at_content)

            text_content = codec.encode_string(1, text)
            text_elem = b''
            text_elem += codec.encode_string(1, "TIMTextElem")
            text_elem += codec.encode_message_field(2, text_content)

            data = b''
            data += codec.encode_string(1, msg_id)
            data += codec.encode_string(2, gc)
            data += codec.encode_string(3, self.bot_id or "")
            data += codec.encode_string(5, str(random.randint(1, 999999999)))
            data += codec.encode_message_field(6, at_elem)
            data += codec.encode_message_field(6, text_elem)
            data += codec.encode_string(7, ref_msg_id)
        else:
            data = codec.encode_send_group_msg_req(
                msg_id=msg_id, group_code=gc,
                from_account=self.bot_id or "", text=text,
                ref_msg_id=ref_msg_id
            )

        head = codec.encode_head(
            cmd_type=proto.CMD_TYPE_REQUEST,
            cmd=proto.BIZ_CMD_SEND_GROUP,
            seq_no=self.seq_no,
            msg_id=self._generate_msg_id(),
            module=proto.BIZ_MODULE
        )
        self.seq_no += 1
        return codec.encode_conn_msg(head, data)

    # ─── 发送 API ──────────────────────────────

    async def send_message(self, text: str, target_group: str = None) -> bool:
        """发送群消息"""
        if not self.connected or not self.ws:
            return False
        try:
            msg = self._build_group_msg(text, target_group)
            await self.ws.send(msg)
            return True
        except Exception as e:
            self._log(f"发送消息失败: {e}")
            return False

    async def send_dm(self, to_account: str, text: str) -> bool:
        """发送私聊消息"""
        if not self.connected or not self.ws:
            return False
        try:
            msg = self._build_dm_msg(to_account, text)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def send_reply(self, text: str, ref_msg_id: str,
                          at_user_id: str = "", at_nickname: str = "",
                          target_group: str = None) -> bool:
        """发送引用回复消息"""
        if not self.connected or not self.ws:
            return False
        try:
            msg = self._build_reply_msg(text, ref_msg_id, at_user_id, at_nickname, target_group)
            await self.ws.send(msg)
            return True
        except Exception:
            return False

    async def fetch_members(self) -> Optional[dict]:
        """获取群成员列表"""
        if not self.connected or not self.ws:
            return None
        try:
            msg_id, msg = self._build_get_members_msg()
            future = asyncio.get_event_loop().create_future()
            self.pending_requests[msg_id] = future
            await self.ws.send(msg)
            try:
                result = await asyncio.wait_for(future, timeout=30)
                return result
            except asyncio.TimeoutError:
                self.pending_requests.pop(msg_id, None)
                return None
        except Exception as e:
            self._log(f"获取成员列表失败: {e}")
            return None

    # ─── 心跳 ──────────────────────────────────

    async def _heartbeat_loop(self):
        while self.connected:
            await asyncio.sleep(70)
            if not self.connected:
                break
            try:
                codec = proto.SimpleProtobufCodec()
                head = codec.encode_head(
                    cmd_type=proto.CMD_TYPE_REQUEST,
                    cmd=proto.CMD_PING,
                    seq_no=self.seq_no,
                    msg_id=self._generate_msg_id(),
                    module=proto.MODULE_CONN_ACCESS
                )
                self.seq_no += 1
                ping_msg = codec.encode_conn_msg(head)
                await self.ws.send(ping_msg)
            except Exception:
                self.connected = False
                break
        if not self._reconnecting:
            await self._auto_reconnect()

    # ─── 接收循环 ──────────────────────────────

    async def _receive_loop(self):
        try:
            while self.connected and self.ws:
                raw = await self.ws.recv()
                if isinstance(raw, bytes):
                    conn_msg = proto.decode_conn_msg(raw)
                    if not conn_msg:
                        continue
                    head = conn_msg.get("head", {})
                    cmd_type = head.get("cmdType")
                    cmd = head.get("cmd", "")
                    msg_id = head.get("msgId")
                    biz_data = conn_msg.get("data", b"")

                    # 推送消息
                    if cmd_type == proto.CMD_TYPE_PUSH:
                        if cmd == "inbound_message" and biz_data:
                            try:
                                push_json = json.loads(biz_data)
                                text_content = ""
                                msg_body = push_json.get("msg_body", [])
                                if msg_body:
                                    for elem in msg_body:
                                        mt = elem.get("msg_type", "")
                                        mc = elem.get("msg_content", {})
                                        if mt == "TIMTextElem":
                                            text_content += mc.get("text", "")
                                        elif mt == "TIMCustomElem":
                                            try:
                                                cd = json.loads(mc.get("data", "{}"))
                                                if cd.get("elem_type") == 1002:
                                                    text_content += cd.get("text", "") + " "
                                            except:
                                                pass

                                sender_name = push_json.get("sender_nickname", "")
                                sender_id = push_json.get("from_account", "")
                                gc = push_json.get("group_code", "")
                                now_str = datetime.now().strftime("%H:%M:%S")

                                cache_entry = {
                                    "time": now_str,
                                    "sender_id": sender_id,
                                    "sender_name": sender_name,
                                    "group_code": gc,
                                    "content": text_content,
                                    "msg_type": push_json.get("callback_command", ""),
                                    "msg_id": push_json.get("msg_id", ""),
                                }
                                self.msg_cache.append(cache_entry)
                                if len(self.msg_cache) > 1000:
                                    self.msg_cache = self.msg_cache[-1000:]

                                # 回调通知
                                if self.on_message:
                                    try:
                                        await self.on_message(cache_entry, push_json)
                                    except Exception:
                                        pass

                            except (json.JSONDecodeError, Exception):
                                pass
                        continue

                    # 响应消息
                    if cmd_type == proto.CMD_TYPE_RESPONSE and msg_id and msg_id in self.pending_requests:
                        future = self.pending_requests.pop(msg_id)
                        if cmd == proto.BIZ_CMD_GET_MEMBERS and biz_data:
                            result = proto.decode_get_group_member_list_rsp(biz_data)
                            if result:
                                result["msg_id"] = msg_id
                                future.set_result(result)
                            else:
                                future.set_result({"msg_id": msg_id, "code": -1, "member_list": []})
                        elif status := head.get("status"):
                            future.set_result({"msg_id": msg_id, "code": status, "message": "FAIL"})
                        else:
                            future.set_result({"msg_id": msg_id, "code": 0})
        except Exception as e:
            self._log(f"接收循环异常: {e}")
        finally:
            self.connected = False
            if self.on_connection_state:
                self.on_connection_state(False)
        if not self._reconnecting:
            await self._auto_reconnect()

    # ─── 自动重连 ──────────────────────────────

    async def _auto_reconnect(self) -> bool:
        if self._reconnecting:
            return False
        self._reconnecting = True
        self.connected = False

        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=1.0)
            except Exception:
                pass
            self.ws = None

        # 清理 pending requests
        pending = list(self.pending_requests.items())
        self.pending_requests.clear()
        for mid, fut in pending:
            if not fut.done():
                fut.set_result({"code": -1, "message": "重连"})

        if self.on_connection_state:
            self.on_connection_state(False)

        self._log("[重连] 正在尝试自动重连...")
        delays = [1, 2, 4, 8, 16]
        for delay in delays:
            self._log(f"[重连] 等待 {delay}s 后重试...")
            await asyncio.sleep(delay)

            self.token = None
            if not self.sign_token():
                continue

            try:
                self.ws = await websockets.connect(self.config.ws_url)
                auth_msg = self._build_auth_bind_msg()
                await self.ws.send(auth_msg)
                await asyncio.wait_for(self.ws.recv(), timeout=10)
                self.connected = True
                self._log("[重连] 重连成功!")

                try:
                    sync_msg = self._build_sync_information_req()
                    await self.ws.send(sync_msg)
                except Exception:
                    pass

                if self.on_connection_state:
                    self.on_connection_state(True)
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                self._recv_task = asyncio.create_task(self._receive_loop())
                self._reconnecting = False
                return True
            except Exception as e:
                self._log(f"[重连] 连接失败: {e}")
                self.ws = None

        self._reconnecting = False
        self._log("[重连] 最大重试次数耗尽，重连失败")
        return False

    # ─── 实用工具 ──────────────────────────────

    async def auto_fetch_members(self) -> bool:
        """静默获取群成员列表"""
        result = await self.fetch_members()
        if result and result.get("code") == 0:
            mlist = result.get("member_list", [])
            for m in mlist:
                uid = m.get("user_id", "")
                nick = m.get("nick_name", "")
                if uid and uid not in self.user_db and nick:
                    self.user_db[uid] = nick
            return True
        return False

    def get_last_messages(self, count: int = 20) -> List[dict]:
        """获取最近 N 条消息"""
        return self.msg_cache[-count:] if self.msg_cache else []

    def set_group(self, group_code: str):
        """切换目标群"""
        self.group_code = group_code
        self.user_db.clear()

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_reconnecting(self) -> bool:
        return self._reconnecting
