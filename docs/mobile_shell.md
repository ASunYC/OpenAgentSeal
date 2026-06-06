# OpenAgentSeal 移动端壳

OpenAgentSeal 提供两种移动访问方式：

- Android 原生壳：APK 内置移动 UI，通过局域网连接电脑端 OpenAgentSeal。
- 移动网页：手机浏览器访问电脑端 `/mobile`，也可在安全上下文中添加到主屏幕。

## 使用条件

1. 手机与电脑连接同一个局域网。
2. 电脑端运行包含移动端功能的 OpenAgentSeal。
3. Windows 防火墙允许 OpenAgentSeal 在专用网络中通信。
4. 默认服务端口为 `9998`。

## 配对

1. 在电脑端打开“设置 → 移动端”。
2. 确认页面显示“局域网监听已开启”。
3. 点击“生成配对码”。
4. 使用手机扫描二维码打开移动网页，或在 Android 壳中输入页面显示的电脑地址与 6 位配对码。
5. 配对成功后，手机可以切换智能体、查看各智能体独立会话、发送消息、停止运行并查看任务状态。

配对码有效期为 3 分钟且只能使用一次。失败尝试次数过多时，服务端会暂时拒绝继续配对。

## 设备管理

已配对设备显示在“设置 → 移动端”中。点击“撤销”后，该设备保存的令牌立即失效，需要重新配对才能连接。

移动端令牌在电脑端以 SHA-256 哈希保存，远程令牌只允许调用移动端所需的会话、运行和停止接口，不能读取模型密钥或修改全局设置。

## Android 构建

```powershell
cd open_agent\app\web
npm run mobile:build
```

Debug APK 输出到：

```text
open_agent/app/web/android/app/build/outputs/apk/debug/app-debug.apk
```

当前工作区还会把测试 APK 复制到：

```text
dist/mobile/OpenAgentSeal-Mobile-debug.apk
```

Android 工程使用 Capacitor，应用 ID 为 `com.openagentseal.mobile`。本机需安装 JDK 21、Android SDK Platform 36 和对应 Build Tools。

## 当前边界

- 当前为 Windows 主机端加 Android 移动壳。
- 暂不提供公网中继，离开同一局域网后无法连接。
- iOS 原生包需要在 macOS/Xcode 环境中生成和签名。
- 普通局域网 HTTP 页面不满足完整 PWA 安全上下文要求，因此 Android 推荐安装 APK。
