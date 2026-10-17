# adb / UI 自动化备忘

## 坐标要先校准，别信截图尺寸

同一台设备，`adb exec-out screencap` 的像素尺寸可能和 `uiautomator dump` 里的逻辑坐标不一致。
**以 dump 里的 `bounds` 为准**：

```bash
adb shell wm size                 # Physical size: 900x1600（竖屏物理）
adb shell uiautomator dump ...    # bounds 可能是 [0,0][1600,900]（横屏逻辑）
```

本套脚本用的常量（1600×900 逻辑坐标）来自实测；换设备请先用一次
`python -c "import wb; [print(n) for n in wb.nodes()]"` 打印真实 bounds 再改。

## 播放页控件（1600×900）

| 控件 | resource-id 尾段 | 中心坐标 |
|---|---|---|
| 返回 | `ViewID_PlayerNavBarBackItem` | (46, 78) |
| 定时关闭 | `ViewID_PlayerToolBarSetTime` | (109, 480) |
| 语速 | `ViewID_PlayerToolBarSetSpeed` | (800, 480) |
| **文稿** | `ViewID_PlayerToolBarLyric` | **(109, 664)** |
| 上一首 | `ViewID_PlayerToolBarPrev` | **(451, 664)** |
| 播放/暂停 | `ViewID_PlayerToolBarPlay` | **(800, 664)** |
| 下一首 | `ViewID_PlayerToolBarNext` | **(1149, 664)** |
| 目录 | `ViewID_PlayerToolBarCatalog` | **(1490, 664)** |

- 当前集标题在 `bounds="[84,350][1516,392]"` 的节点的 **content-desc** 里（`text` 常为空）。
- 播放按钮的 content-desc：`播放` = 当前已暂停，`暂停` = 当前正在播放。
- 有播放条悬浮时另有 `toolbar_player_tv_duration` / `player_bar_play` / `player_bar_close`。

## 文稿页

- 根节点：`album_stt_top_info_view_id`（顶栏，含返回 + 专辑名）、`album_stt_recycler_view_id`（正文）
- **正文文字不暴露在 dump 里**（自绘控件，只有空节点），所以只能：
  - 走缓存（首选），或
  - 截图做像素分析 / 长按选区复制（兜底）

## 坑：adb daemon 被回收

某些环境下每次命令块结束 adb server 会被杀掉，下次调用报
`device 'xxx' not found` + `daemon not running; starting now`。
所以每个脚本开头都 `adb start-server && adb connect`，不要假设连接还在。

## 坑：dump 拿到旧界面

播放器有封面动画时 `uiautomator dump` 会输出 `ERROR: could not get idle state.`，
**并且不会覆盖旧的 `/sdcard/_u.xml`**，于是你读到的是上一个界面——非常容易误判。
`wb.rdump()` 的做法：先 `rm -f` 再 dump，检查输出无 `ERROR`，最多重试 8 次。
读不到就先**暂停播放**，动画停了 dump 立刻正常。

## 坑：播放进度会改变界面状态

- 一集播完自动跳下一集 → 文稿页跟着换 → 采到的内容不是你以为的那一集
- 文稿页自动滚动 → 选区/位置漂移

**任何"读当前集内容"的操作前都先 `wb.pause()`，并在切集后重新核对 `wb.cur_title()`。**

## 兜底方案：缓存完全拿不到时用 UI 复制

仅在应用没落库、又必须拿到文字时使用（慢，成功率约 40–60%）。

1. 滚到要采的位置，**暂停**
2. 长按：`input swipe X Y X Y 1100`（原地长按 1.1 秒）
3. 扩选：`input draganddrop X Y X 185 3000`——从底部文字往上拖，可整屏选中
4. 浮窗菜单是深色圆角矩形（此主题下均匀灰 rgb≈51,51,51），**第 2 个按钮才是「复制」**
5. 读剪贴板：Android 12 起 shell 无权读剪贴板，绕法是
   切 Chrome → 点地址栏 → 长按 → 点「粘贴」→ `uiautomator dump` 读 `android.widget.EditText` 的 `text`
   （粘贴后 URL 前缀要按 `wd=` / `word=` / `q=` 剥掉）
6. 回微信读书用 `am force-stop com.android.chromium`，**不要用 monkey 重启**（会丢页面位置）

## 深色模式截图分析（无多模态时的土办法）

不能看图时，用 ffmpeg 把 png 转 `rawvideo rgb24` 再按像素判断：

```bash
ffmpeg -i shot.png -f rawvideo -pix_fmt rgb24 shot.raw
```

实测配色：背景 `(21,21,21)`、选中文字底色 `(23,36,47)`、选区手柄亮蓝 `(0,157,247)`、
浮窗菜单灰 `(51,51,51)`。可以据此把截图降采样成 ASCII 图来看版式。
