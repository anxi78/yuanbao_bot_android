[app]
title = 元宝 Bot
package.name = yuanbaobot
package.domain = com.yuanbao.bot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
version = 0.1
requirements = python3,kivy,aiohttp
orientation = portrait
osx.python_version = 3
osx.kivy_version = 2.2.0
fullscreen = 0

# Android specific
android.api = 33
android.minapi = 21
android.sdk = 33
android.ndk = 26.3.11579264
android.permissions = INTERNET
android.archs = arm64-v8a
android.add_src =

# iOS specific
ios.codesign.allowed = false

[buildozer]
log_level = 2
warn_on_root = 1
