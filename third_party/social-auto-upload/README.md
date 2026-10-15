# social-auto-upload 接入

上游为 [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload)，固定 commit `0012d2c355f88f683cc38dde2a2db209e14091bc`，保留 [MIT 原许可证](LICENSE)。`local-fixes.patch` 是本项目在该版本上的当前修改，包含 Playwright 依赖、提交标识、小红书就绪检查和转载选项、YouTube 完成检查与代理处理。`tests/` 为补充回归测试。

在仓库根安装，不进行登录或发布：

```sh
git clone https://github.com/dreammis/social-auto-upload.git GitHub/social-auto-upload
git -C GitHub/social-auto-upload checkout 0012d2c355f88f683cc38dde2a2db209e14091bc
git -C GitHub/social-auto-upload apply --check ../../third_party/social-auto-upload/local-fixes.patch
git -C GitHub/social-auto-upload apply ../../third_party/social-auto-upload/local-fixes.patch
cp third_party/social-auto-upload/tests/*.py GitHub/social-auto-upload/tests/
python3.12 -m venv GitHub/social-auto-upload/.venv
GitHub/social-auto-upload/.venv/bin/python -m pip install -e GitHub/social-auto-upload
GitHub/social-auto-upload/.venv/bin/python -m playwright install chromium
```

上游源码、虚拟环境与 `cookies/` 留在本机，被根 `.gitignore` 排除。不要直接覆盖补丁后假设上传行为仍相同。按 [发布说明](../../docs/publishing.md) 配置自己的账号。
