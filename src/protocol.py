"""
元宝 Bot 协议核心 - 纯 Python Protobuf 编解码
直接从 sender.py 提取，保持兼容
"""
import json
import random
import struct
import uuid
from typing import Optional, Dict, List


# ─── Protobuf 编解码（纯标准库）──────────────────────

def pb_varint(value):
    if value < 0:
        value = (1 << 64) + value
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def pb_tag(field, wire):
    return pb_varint((field << 3) | wire)


def pb_string(field, value):
    data = value.encode("utf-8")
    return pb_tag(field, 2) + pb_varint(len(data)) + data


def pb_bytes(field, value):
    return pb_tag(field, 2) + pb_varint(len(value)) + value


def pb_int32(field, value):
    return pb_tag(field, 0) + pb_varint(value)


def pb_uint32(field, value):
    return pb_tag(field, 0) + pb_varint(value)


def pb_msg(field, inner):
    return pb_tag(field, 2) + pb_varint(len(inner)) + inner


def pb_decode_varint(data, off=0):
    result = 0
    shift = 0
    while off < len(data):
        b = data[off]
        result |= (b & 0x7F) << shift
        off += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, off


def pb_decode_delimited(data, off=0):
    length, off = pb_decode_varint(data, off)
    return data[off:off + length], off + length


def pb_decode_msg(data):
    result = {}
    off = 0
    while off < len(data):
        tag, off = pb_decode_varint(data, off)
        field = tag >> 3
        wire = tag & 7
        if wire == 0:
            val, off = pb_decode_varint(data, off)
            result[field] = (0, val)
        elif wire == 2:
            val, off = pb_decode_delimited(data, off)
            result[field] = (2, val)
        elif wire == 5:
            val = struct.unpack_from("<I", data, off)[0]
            off += 4
            result[field] = (5, val)
        elif wire == 1:
            val = struct.unpack_from("<Q", data, off)[0]
            off += 8
            result[field] = (1, val)
        else:
            break
    return result


# ─── 连接层（ConnMsg）──────────────────────────────

def encode_conn_head(cmd_type, cmd, seq_no, msg_id, module):
    head = b""
    head += pb_int32(1, cmd_type)
    head += pb_string(2, cmd)
    head += pb_int32(3, seq_no)
    head += pb_string(4, msg_id)
    head += pb_string(5, module)
    return head


def encode_conn_msg(cmd_type, cmd, seq_no, msg_id, module, data=b""):
    frame = pb_msg(1, encode_conn_head(cmd_type, cmd, seq_no, msg_id, module))
    if data:
        frame += pb_bytes(2, data)
    return frame


def decode_conn_msg(data):
    msg = pb_decode_msg(data)
    result = {}
    if 1 in msg:
        head = pb_decode_msg(msg[1][1])
        for fid, key in [(1, "cmdType"), (2, "cmd"), (3, "seqNo"), (4, "msgId"), (5, "module")]:
            if fid in head:
                val = head[fid][1]
                result[key] = val.decode("utf-8", errors="replace") if isinstance(val, bytes) else val
    if 2 in msg:
        result["data"] = msg[2][1]
    return result


# ─── 鉴权 ─────────────────────────────────────────

def encode_auth_bind(biz_id, uid, source, token):
    auth_info = pb_string(1, uid) + pb_string(2, source) + pb_string(3, token)
    device_info = (
        pb_string(1, "2.0.1")
        + pb_string(2, "Linux")
        + pb_string(3, "2026.3.23-2")
        + pb_string(4, "16")
    )
    return pb_string(1, biz_id) + pb_msg(2, auth_info) + pb_msg(3, device_info)


# ─── 消息体 ───────────────────────────────────────

def encode_msg_body_element(msg_type, text):
    msg_content = pb_string(1, text)
    return pb_string(1, msg_type) + pb_msg(2, msg_content)


def encode_send_group_req(group_code, text, msg_id="", from_account="", random_val=None):
    if random_val is None:
        random_val = str(random.randint(0, 2**32 - 1))
    body_elem = encode_msg_body_element("TIMTextElem", text)
    req = b""
    req += pb_string(1, msg_id)
    req += pb_string(2, group_code)
    req += pb_string(3, from_account)
    req += pb_string(4, "")
    req += pb_string(5, random_val)
    req += pb_msg(6, body_elem)
    req += pb_string(7, "")
    return req


def encode_send_c2c_req(to_account, text, msg_id="", from_account="", msg_random=None):
    if msg_random is None:
        msg_random = random.randint(0, 2**32 - 1)
    body_elem = encode_msg_body_element("TIMTextElem", text)
    req = b""
    req += pb_string(1, msg_id)
    req += pb_string(2, to_account)
    req += pb_string(3, from_account)
    req += pb_uint32(4, msg_random)
    req += pb_msg(5, body_elem)
    return req


def decode_send_group_rsp(data):
    msg = pb_decode_msg(data)
    result = {}
    if 1 in msg:
        result["code"] = msg[1][1]
    if 2 in msg:
        result["message"] = msg[2][1].decode("utf-8", errors="replace")
    if 3 in msg:
        result["msgId"] = msg[3][1].decode("utf-8", errors="replace")
    if 4 in msg:
        result["msgSeq"] = msg[4][1]
    return result


def decode_send_c2c_rsp(data):
    msg = pb_decode_msg(data)
    result = {}
    if 1 in msg:
        result["code"] = msg[1][1]
    if 2 in msg:
        result["message"] = msg[2][1].decode("utf-8", errors="replace")
    return result


# ─── 富媒体元素 ───────────────────────────────────

def encode_tim_image_elem(url, uuid_str="", size=0, width=0, height=0, image_format=255):
    img_info = (
        pb_uint32(1, 1) +
        pb_uint32(2, size) +
        pb_uint32(3, width) +
        pb_uint32(4, height) +
        pb_string(5, url)
    )
    mc = b""
    if uuid_str:
        mc += pb_string(2, uuid_str)
    mc += pb_uint32(3, image_format) + pb_msg(8, img_info)
    return pb_string(1, "TIMImageElem") + pb_msg(2, mc)


def encode_tim_face_elem(sticker_id, package_id, name, width=128, height=128, formats="png"):
    data_json = json.dumps({
        "sticker_id": sticker_id, "package_id": package_id,
        "width": width, "height": height,
        "formats": formats, "name": name,
    }, ensure_ascii=False)
    msg_content = pb_uint32(9, 0) + pb_string(4, data_json)
    return pb_string(1, "TIMFaceElem") + pb_msg(2, msg_content)


def encode_tim_file_elem(url, uuid_str="", file_size=0, file_name=""):
    mc = b""
    if uuid_str:
        mc += pb_string(2, uuid_str)
    mc += pb_string(10, url)
    if file_size:
        mc += pb_uint32(11, file_size)
    if file_name:
        mc += pb_string(12, file_name)
    return pb_string(1, "TIMFileElem") + pb_msg(2, mc)


def encode_get_group_member_list_req(group_code):
    return pb_string(1, group_code)


def decode_get_group_member_list_rsp(data):
    msg = pb_decode_msg(data)
    result = {"code": 0, "message": "", "member_list": []}
    if 1 in msg:
        result["code"] = msg[1][1]
    if 2 in msg:
        result["message"] = msg[2][1].decode("utf-8", errors="replace")
    if 3 in msg:
        pass  # 简化解码
    return result


# ─── 协议常量 ─────────────────────────────────────

CMD_TYPE_REQUEST = 0
CMD_TYPE_RESPONSE = 1
CMD_TYPE_PUSH = 2
CMD_TYPE_PUSH_ACK = 3

CMD_AUTH_BIND = "auth-bind"
CMD_PING = "ping"
MODULE_CONN_ACCESS = "conn_access"
BIZ_MODULE = "yuanbao_openclaw_proxy"
BIZ_CMD_SEND_C2C = "send_c2c_message"
BIZ_CMD_SEND_GROUP = "send_group_message"
BIZ_CMD_GET_MEMBERS = "get_group_member_list"
BIZ_CMD_QUERY_GROUP_INFO = "query_group_info"
BIZ_CMD_SYNC_INFORMATION = "sync_information"


# ─── 消息推送解码 ─────────────────────────────────

def decode_inbound_message_push(data):
    """解码 InboundMessagePush - 收到的消息"""
    result = {}
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        tag = data[pos]
        pos += 1
        field_num = tag >> 3
        wire_type = tag & 0x07

        if field_num == 1 and wire_type == 2:  # callbackCommand
            length, pos = pb_decode_varint(data, pos)
            result['callbackCommand'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 2 and wire_type == 2:  # fromAccount
            length, pos = pb_decode_varint(data, pos)
            result['fromAccount'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 3 and wire_type == 2:  # toAccount
            length, pos = pb_decode_varint(data, pos)
            result['toAccount'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 4 and wire_type == 2:  # senderNickname
            length, pos = pb_decode_varint(data, pos)
            result['senderNickname'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 5 and wire_type == 2:  # groupCode
            length, pos = pb_decode_varint(data, pos)
            result['groupCode'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 6 and wire_type == 2:  # groupName
            length, pos = pb_decode_varint(data, pos)
            result['groupName'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 9 and wire_type == 0:  # msgTime
            result['msgTime'], pos = pb_decode_varint(data, pos)
        elif field_num == 11 and wire_type == 2:  # msgId
            length, pos = pb_decode_varint(data, pos)
            result['msgId'] = data[pos:pos+length].decode('utf-8')
            pos += length
        elif field_num == 12 and wire_type == 2:  # msgBody
            length, pos = pb_decode_varint(data, pos)
            msg_body_data = data[pos:pos+length]
            pos += length
            try:
                text = _extract_text_from_msg_body(msg_body_data)
                if text:
                    result['text'] = text
            except Exception:
                pass
        else:
            if wire_type == 0:
                _, pos = pb_decode_varint(data, pos)
            elif wire_type == 2:
                length, pos = pb_decode_varint(data, pos)
                pos += length
            else:
                break
    return result


def _extract_text_from_msg_body(data):
    """从 MsgBodyElement 中提取文本"""
    pos = 0
    while pos < len(data):
        if pos >= len(data):
            break
        tag = data[pos]
        pos += 1
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num == 2 and wire_type == 2:  # msgContent
            length, pos = pb_decode_varint(data, pos)
            content_data = data[pos:pos+length]
            pos += length
            cpos = 0
            while cpos < len(content_data):
                if cpos >= len(content_data):
                    break
                ctag = content_data[cpos]
                cpos += 1
                cfield = ctag >> 3
                cwire = ctag & 0x07
                if cfield == 1 and cwire == 2:  # text
                    tlen, cpos = pb_decode_varint(content_data, cpos)
                    text = content_data[cpos:cpos+tlen].decode('utf-8')
                    return text
                elif cwire == 0:
                    _, cpos = pb_decode_varint(content_data, cpos)
                elif cwire == 2:
                    tlen, cpos = pb_decode_varint(content_data, cpos)
                    cpos += tlen
                else:
                    break
        elif wire_type == 0:
            _, pos = pb_decode_varint(data, pos)
        elif wire_type == 2:
            length, pos = pb_decode_varint(data, pos)
            pos += length
        else:
            break
    return None


# ─── High-level API ──────────────────────────────

class SimpleProtobufCodec:
    """简化版 Protobuf 编解码器（与 sender.py 完全兼容）"""

    @staticmethod
    def encode_varint(value: int) -> bytes:
        return pb_varint(value)

    @staticmethod
    def encode_string(field_num: int, value: str) -> bytes:
        return pb_string(field_num, value)

    @staticmethod
    def encode_message_field(field_num: int, encoded_msg: bytes) -> bytes:
        return pb_msg(field_num, encoded_msg)

    @staticmethod
    def encode_tim_image_elem(url, uuid="", size=0, width=0, height=0, image_format=255):
        return encode_tim_image_elem(url, uuid, size, width, height, image_format)

    @staticmethod
    def encode_tim_face_elem(sticker_id, package_id, name,
                              width=128, height=128, formats="png"):
        return encode_tim_face_elem(sticker_id, package_id, name,
                                     width, height, formats)

    @staticmethod
    def encode_tim_file_elem(url, uuid="", file_size=0, file_name=""):
        return encode_tim_file_elem(url, uuid, file_size, file_name)

    @staticmethod
    def encode_head(cmd_type, cmd, seq_no, msg_id, module) -> bytes:
        return encode_conn_head(cmd_type, cmd, seq_no, msg_id, module)

    @staticmethod
    def encode_conn_msg(head, data=b''):
        decoded = SimpleProtobufCodec.decode_head(head)
        cmd_type = decoded.get("cmd_type", 0)
        cmd = decoded.get("cmd", "")
        seq_no = decoded.get("seq_no", 0)
        msg_id = decoded.get("msg_id", "")
        module = decoded.get("module", "")
        return encode_conn_msg(cmd_type, cmd, seq_no, msg_id, module, data)

    @staticmethod
    def encode_auth_bind_req(biz_id, uid, source, token):
        return encode_auth_bind(biz_id, uid, source, token)

    @staticmethod
    def encode_send_group_msg_req(msg_id, group_code, from_account, text, ref_msg_id=""):
        return encode_send_group_req(group_code, text, msg_id, from_account)

    @staticmethod
    def encode_send_c2c_msg_req(msg_id, to_account, from_account, text):
        return encode_send_c2c_req(to_account, text, msg_id, from_account)

    @staticmethod
    def encode_get_group_member_list_req(group_code):
        return encode_get_group_member_list_req(group_code)

    @staticmethod
    def decode_get_group_member_list_rsp(data):
        return decode_get_group_member_list_rsp(data)

    @staticmethod
    def decode_varint(data, pos=0):
        return pb_decode_varint(data, pos)

    @staticmethod
    def decode_inbound_message_push(data):
        return decode_inbound_message_push(data)

    @staticmethod
    def decode_conn_msg(data):
        return decode_conn_msg(data)

    @staticmethod
    def decode_head(data):
        """解码 Head 消息"""
        head = {"cmd_type": 0}
        i = 0
        while i < len(data):
            tag = data[i]
            i += 1
            field_num = tag >> 3
            wire_type = tag & 7
            if wire_type == 0:
                value = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    value |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                if field_num == 1:
                    head["cmd_type"] = value
                elif field_num == 3:
                    head["seq_no"] = value
                elif field_num == 10:
                    head["status"] = value
            elif wire_type == 2:
                length = 0
                shift = 0
                while True:
                    if i >= len(data):
                        break
                    byte = data[i]
                    i += 1
                    length |= (byte & 0x7f) << shift
                    if not (byte & 0x80):
                        break
                    shift += 7
                field_data = data[i:i+length]
                i += length
                if field_num == 2:
                    head["cmd"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 4:
                    head["msg_id"] = field_data.decode('utf-8', errors='replace')
                elif field_num == 5:
                    head["module"] = field_data.decode('utf-8', errors='replace')
        return head