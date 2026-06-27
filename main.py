"""
元宝 Bot - Kivy Android 客户端
"""
import asyncio
import json
import os

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.properties import StringProperty, BooleanProperty, ListProperty

from src.bot_client import BotClient

# ─── KV 布局 ────────────────────────────────────

KV = '''
<ConfigPopup>:
    title: '设置'
    size_hint: 0.85, 0.7
    auto_dismiss: False
    BoxLayout:
        orientation: 'vertical'
        padding: dp(12)
        spacing: dp(8)
        Label:
            text: 'Bot ID'
            size_hint_y: None
            height: dp(24)
        TextInput:
            id: bot_id
            text: app.config_bot_id
            multiline: False
        Label:
            text: '群 Code'
            size_hint_y: None
            height: dp(24)
        TextInput:
            id: group_code
            text: app.config_group_code
            multiline: False
        Label:
            text: 'Token 签名 URL (可选)'
            size_hint_y: None
            height: dp(24)
        TextInput:
            id: token_url
            text: app.config_token_url
            hint_text: '留空使用本地签名'
            multiline: False
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(8)
            Button:
                text: '保存并连接'
                on_release:
                    app.save_config(bot_id.text, group_code.text, token_url.text)
                    app.dismiss_popup()
            Button:
                text: '取消'
                on_release:
                    app.dismiss_popup()

<MainLayout>:
    orientation: 'vertical'
    padding: dp(2)
    spacing: dp(2)

    # 顶栏
    BoxLayout:
        size_hint_y: None
        height: dp(48)
        spacing: dp(4)
        padding: [dp(4), dp(4)]
        canvas.before:
            Color:
                rgba: 0.12, 0.12, 0.12, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Button:
            text: '⚙'
            size_hint_x: None
            width: dp(48)
            on_release: app.show_config()
        Label:
            id: status_label
            text: app.status_text
            color: app.status_color
            bold: True
            halign: 'center'
        Button:
            text: '连接' if not app.bot_connected else '断开'
            size_hint_x: None
            width: dp(64)
            on_release: app.toggle_connection()

    # 消息列表
    BoxLayout:
        orientation: 'vertical'
        ScrollView:
            id: msg_scroll
            do_scroll_y: True
            BoxLayout:
                id: msg_container
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                padding: dp(4)
                spacing: dp(2)

    # 快捷贴纸栏 (折叠式)
    BoxLayout:
        id: sticker_bar
        size_hint_y: None
        height: dp(0)
        orientation: 'horizontal'
        opacity: 0

    # 输入区
    BoxLayout:
        size_hint_y: None
        height: dp(56)
        spacing: dp(4)
        padding: [dp(4), dp(4)]
        TextInput:
            id: cmd_input
            hint_text: '输入命令或消息...'
            multiline: False
            on_text_validate:
                app.send_command(self.text)
                self.text = ''
        Button:
            text: '发送'
            size_hint_x: None
            width: dp(60)
            on_release:
                app.send_command(cmd_input.text)
                cmd_input.text = ''
        Button:
            text: '😊'
            size_hint_x: None
            width: dp(48)
            on_release: app.toggle_stickers()
'''


class MainLayout(BoxLayout):
    """主界面布局 (由 KV 自动构建)"""
    pass


class ConfigPopup(Popup):
    """配置弹窗"""
    pass


class YuanbaoBotApp(App):
    """元宝 Bot Kivy 应用"""

    status_text = StringProperty("未连接")
    status_color = ListProperty([0.8, 0.2, 0.2, 1])  # 红
    bot_connected = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bot: BotClient = None
        self.config_bot_id = ""
        self.config_group_code = ""
        self.config_token_url = ""
        self._popup = None
        self._config_file = self._get_config_path()
        self._sticker_visible = False
        self._load_config()

    def _get_config_path(self) -> str:
        """获取配置文件路径"""
        return os.path.join(os.path.dirname(__file__), "config.json")

    def build(self):
        self.title = "元宝 Bot"
        self.use_kivy_settings = False
        root = Builder.load_string(KV)
        return root

    def on_start(self):
        """应用启动"""
        if self.config_bot_id and self.config_group_code:
            Clock.schedule_once(lambda dt: self._init_bot(), 0.5)

    def on_stop(self):
        """应用停止"""
        if self.bot:
            asyncio.ensure_future(self.bot.stop())

    # ─── 配置 ─────────────────────────────────

    def _load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, "r") as f:
                    cfg = json.load(f)
                self.config_bot_id = cfg.get("bot_id", "")
                self.config_group_code = cfg.get("group_code", "")
                self.config_token_url = cfg.get("sign_token_url", "")
        except Exception:
            pass

    def save_config(self, bot_id: str, group_code: str, token_url: str):
        """保存配置"""
        self.config_bot_id = bot_id
        self.config_group_code = group_code
        self.config_token_url = token_url
        try:
            os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
            with open(self._config_file, "w") as f:
                json.dump({
                    "bot_id": bot_id,
                    "group_code": group_code,
                    "sign_token_url": token_url,
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._add_log(f"保存配置失败: {e}")
        self._init_bot()

    def show_config(self):
        """显示配置弹窗"""
        popup = ConfigPopup()
        popup.app = self
        self._popup = popup
        popup.open()

    def dismiss_popup(self):
        if self._popup:
            self._popup.dismiss()
            self._popup = None

    # ─── BotClient 初始化 ─────────────────────

    def _init_bot(self):
        """创建 BotClient 实例"""
        if self.bot:
            asyncio.ensure_future(self.bot.stop())

        self.bot = BotClient(
            bot_id=self.config_bot_id,
            group_code=self.config_group_code,
            sign_token_url=self.config_token_url,
        )
        self.bot.on_log = self._on_bot_log
        self.bot.on_message = self._on_bot_message
        self.bot.on_connection_change = self._on_connection_change
        self.bot.on_error = self._on_bot_error

        # 启动 bot
        asyncio.ensure_future(self.bot.start())

    # ─── BotClient 回调 ──────────────────────

    def _on_bot_log(self, msg: str):
        """日志回调 -> 在主线程更新 UI"""
        Clock.schedule_once(lambda dt: self._add_log(msg))

    def _on_bot_message(self, msg: dict):
        """消息回调 -> 在主线程更新 UI"""
        Clock.schedule_once(lambda dt: self._add_message(msg))

    def _on_connection_change(self, connected: bool):
        """连接状态变化回调"""
        self.bot_connected = connected
        Clock.schedule_once(lambda dt: self._update_status(connected))

    def _on_bot_error(self, error: str):
        """错误回调"""
        Clock.schedule_once(lambda dt: self._add_log(f"错误: {error}"))

    # ─── UI 更新 ────────────────────────────

    def _update_status(self, connected: bool):
        """更新状态栏"""
        if connected:
            self.status_text = "已连接"
            self.status_color = [0.2, 0.8, 0.2, 1]  # 绿
        else:
            self.status_text = "未连接"
            self.status_color = [0.8, 0.2, 0.2, 1]  # 红

    def _add_log(self, text: str):
        """添加日志消息到界面"""
        if text == "__CLEAR__":
            self._clear_messages()
            return
        container = self.root.ids.msg_container
        label = Label(
            text=text,
            size_hint_y=None,
            height=dp(20),
            text_size=(self.root.width - dp(20), None),
            color=[0.6, 0.6, 0.6, 1],
            font_size="12sp",
            halign="left",
            valign="middle",
        )
        label.bind(texture_size=lambda lb, val: setattr(lb, "height", max(dp(20), lb.texture_size[1])))
        container.add_widget(label)
        self._scroll_to_bottom()

    def _add_message(self, msg: dict):
        """添加消息到界面"""
        text = msg.get("text", "")
        nickname = msg.get("nickname", "")
        sender = msg.get("sender", "")

        # 自动回复
        if self.bot and self.bot.auto_reply_text:
            if sender != self.config_bot_id:
                asyncio.ensure_future(
                    self.bot.send_group_message(self.bot.auto_reply_text)
                )

        display = f"{nickname}: {text}" if nickname else f"{sender}: {text}"
        container = self.root.ids.msg_container
        label = Label(
            text=display,
            size_hint_y=None,
            height=dp(24),
            text_size=(self.root.width - dp(20), None),
            color=[1, 1, 1, 1],
            font_size="14sp",
            halign="left",
            valign="middle",
        )
        label.bind(texture_size=lambda lb, val: setattr(lb, "height", max(dp(24), lb.texture_size[1])))
        container.add_widget(label)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """滚动到消息列表底部"""
        scroll = self.root.ids.msg_scroll
        Clock.schedule_once(lambda dt: setattr(scroll, "scroll_y", 0), 0.05)

    def _clear_messages(self):
        """清空消息列表"""
        self.root.ids.msg_container.clear_widgets()

    # ─── 操作 ───────────────────────────────

    def send_command(self, text: str):
        """发送命令或消息"""
        if not text.strip():
            return
        if not self.bot:
            self._add_log("Bot 未初始化，请先设置配置")
            return
        asyncio.ensure_future(self.bot.queue_command(text.strip()))

    def toggle_connection(self):
        """切换连接状态"""
        if not self.bot:
            self._add_log("请先设置配置")
            self.show_config()
            return
        if self.bot_connected:
            asyncio.ensure_future(self.bot.stop())
        else:
            asyncio.ensure_future(self.bot.start())

    def toggle_stickers(self):
        """切换贴纸栏显示"""
        self._sticker_visible = not self._sticker_visible
        bar = self.root.ids.sticker_bar
        if self._sticker_visible and self.bot:
            # 构建贴纸按钮
            bar.clear_widgets()
            bar.height = dp(48)
            bar.opacity = 1
            names = sorted(self.bot.stickers.keys())[:20]  # 前 20 个
            for name in names:
                btn = Button(
                    text=name[:4],
                    font_size="10sp",
                    size_hint_x=None,
                    width=dp(48),
                )
                sticker_name = name
                btn.bind(on_release=lambda b, n=sticker_name: self._send_sticker(n))
                bar.add_widget(btn)
        else:
            bar.height = dp(0)
            bar.opacity = 0
            bar.clear_widgets()

    def _send_sticker(self, name: str):
        """发送贴纸"""
        if self.bot:
            asyncio.ensure_future(self.bot.queue_command(f"/sticker {name}"))


# ─── 辅助函数 ─────────────────────────────────

def dp(value):
    """模拟 kivy.metrics.dp 的缩放"""
    from kivy.metrics import dp as _dp
    return _dp(value)


# ─── 入口 ─────────────────────────────────────

if __name__ == "__main__":
    YuanbaoBotApp().run()
