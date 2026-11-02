[app]
title = MalO
package.name = malo
package.domain = local.malo
source.dir = .
source.include_exts = py,png,jpg,mp3,json,md
source.exclude_dirs = tests,evals,.git,__pycache__,malo/ui/tk
version = 1.0
requirements = python3,kivy,pillow,requests,urllib3,certifi,chardet,plyer,openssl
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.allow_backup = True