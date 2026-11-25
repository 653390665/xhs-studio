"""应用版本号（唯一来源）。

为什么单独一个文件
------------------
打包后 ``launcher.py`` 是 PyInstaller 的**入口脚本**，它的代码被编进主 exe，
不能再 ``from launcher import APP_VERSION``（模块不存在，会 ImportError）。
所以版本号必须放在一个普通模块里，两边都能 import：

    launcher.py        -> from version import APP_VERSION
    backend/app/main.py-> from version import APP_VERSION   (/api/health 回读)

``packaging/installer.py`` 是单独打的 onefile，不 import 这个模块，
它自己保留一份 APP_VERSION，构建时和这里一起被 tag 改写。
"""

APP_VERSION = "1.2.3"
