# -*- coding: utf-8 -*-
"""测试夹具修补：tmp_path 用「常规权限目录」。

为什么需要：pytest 默认以 `mode=0o700` 建 tmp_path，本机（Windows +
DSH 沙箱）对该目录 ACL 判定为不可写——整套测试会在 setup 阶段全红
（PermissionError: WinError 5），与项目代码无关（README 附录记过同款
坑，`--basetemp` 治不了，因为每个用例的目录仍是 0o700）。

为什么不用 `tempfile.mkdtemp()`：本机实测 mkdtemp 建的目录同样不可写，
`os.chmod(d, 0o777)` 直接 WinError 5（沙箱拒改 ACL）——2026-10-29 复现。
唯一可行的是 `os.makedirs()`（不带 mode）落到工作区内，所以临时目录只能
放在 `<repo>/tmp/pytest/`（`tmp/` 已在 .gitignore 里，不污染工作树）。
"""
import os
import pathlib
import shutil
import uuid

import pytest


@pytest.fixture(scope="session")
def _tmp_root(request):
    root = os.path.join(str(request.config.rootpath), "tmp", "pytest")
    os.makedirs(root, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)   # 尽力而为：锁文件会留残骸


@pytest.fixture
def tmp_path(_tmp_root):
    d = os.path.join(_tmp_root, uuid.uuid4().hex)
    os.makedirs(d)                     # 不用 mode=0o700（见文件头）
    yield pathlib.Path(d)
    shutil.rmtree(d, ignore_errors=True)
