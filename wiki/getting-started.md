# 快速上手

## 前提条件

- AstrBot >= 4.5.7
- 一个 Codecks 账号

## 第一步：安装插件

将插件目录放入 AstrBot 的 `data/plugins/` 下：

```bash
cd <AstrBot 数据目录>/plugins/
git clone https://github.com/AstrBotDevs/astrbot_plugin_codecks_connector.git
```

AstrBot 启动时会自动安装 `requirements.txt` 中的依赖（`aiohttp`）。

## 第二步：获取 Token

1. 用浏览器登录 [Codecks](https://www.codecks.io/)
2. 按 `F12` 打开开发者工具，切到 **Network** 标签
3. 在 Codecks 中做任意操作（比如点击一张卡片）
4. 在 Network 面板中找到发往 `api.codecks.io` 的请求
5. 在请求头的 Cookie 中找到 `at=xxxx`，复制 `xxxx` 部分

> ⚠️ **安全提示**：此 Token 等同于你的登录身份。如果用于自动化脚本，建议创建一个专用的 Observer 用户，使用它的 Token。

## 第三步：获取子域名

你的组织 URL 形如 `https://team123.codecks.io`，则子域名为 `team123`。

## 第四步：配置插件

在 AstrBot WebUI → 插件管理 → Codecks Connector 中填入：

- **Token**：上一步获取的值
- **子域名**：你的组织子域名

## 第五步：测试连接

在聊天中发送：

```
/ck debug
```

如果看到 `✅ 连接成功！` 并显示你的组织名称，说明配置正确。

## 开始使用

```
/ck help          ← 查看所有命令
/ck projects      ← 列出项目
/ck cards         ← 列出最新卡片
/ck hand          ← 查看我的待办
/ck stats         ← 查看统计数据
```

详细命令说明请参考 [命令参考](commands.md)。
