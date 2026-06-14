# Local Video Renamer 系统结构说明

本文档用于帮助开发者或 AI 快速理解项目结构、模块职责和数据流。修改代码前请先阅读本文件，优先保持现有分层，不要把业务逻辑重新堆回 GUI 或 HTTP 路由文件里。

## 一句话概览

这是一个本地视频规范化工具：PyQt GUI 只负责界面和按钮交互，所有扫描、匹配、重命名、CSV 读取、SQLite 台账操作都通过本地 HTTP 后端完成。

```text
PyQt GUI
  -> backend_client.py
  -> http://127.0.0.1:8766
  -> backend_server.py
  -> backend_service.py
  -> video_renamer_api.py / actor_identifier.py / path_library.py / avfan_scraper.py / database_handler.py
  -> CSV / SQLite DB / 本地文件系统
```

## 2026-05 登录态检测补充

- 新增 `login_status_service.py`，专门负责：
  - 进入主页后点击右上角用户图标
  - 判断当前是“已登录”还是“未登录”
  - 未登录时自动跳转登录页并填充本地 `.env` 中的账号密码
  - 等待用户手动完成图片验证码和最终登录
- `auto_login_service.py` 现在只负责调度，不再直接写页面细节。
- 自动登录开始时会切换到一个干净的新标签页，不再沿用上次停留在视频详情页的旧标签页。
- `avfan_scraper.py` 在进入主页准备搜索前，会先调用登录态检测；检测到已登录则继续搜索，检测到未登录则触发登录流程。

## 核心设计原则

- GUI 不直接读取 CSV、SQLite，也不直接执行重命名业务。
- HTTP 路由层只负责解析请求和返回 JSON，不写业务规则。
- 业务协调层负责组织扫描、重命名、数据库保存等流程。
- 独立规则放独立模块，例如文件名清洗、CSV 加载、数据模型。
- 演员识别独立放在 `actor_identifier.py`，不要混进 GUI 或数据库查询页面。
- 路径库业务独立放在 `path_library.py`，GUI 只负责展示、添加、删除和选择。
- AVFan 网页抓取独立放在 `avfan_scraper.py`，补全批处理独立放在 `video_enrichment.py`。
- `.csv` 和 `.db` 是个人本地数据，不应提交到 Git。
- `.env` 保存本地网页访问配置，也不应提交到 Git。
- `browser_profiles/` 保存网页登录状态、Cookie 等个人敏感数据，也不应提交到 Git。

## 模块职责

### `Local_Video_gui.py`

PyQt 主界面入口。

职责：
- 创建主窗口、按钮、路径输入框和扫描结果表格。
- 启动时检查本地后端是否可用，不可用则自动拉起 `backend_server.py`。
- 用户点击按钮后，通过 `BackendClient` 调用后端接口。
- 提供“重置网页登录”按钮，用于清理 AVFan 专用浏览器登录档案。
- 提供“自动登录”按钮，用于打开登录页并自动填入本地 `.env` 中保存的账号密码。
- 补全信息通过后台线程执行，避免 PyQt 主线程阻塞导致窗口“未响应”。
- 提供“停止补全”按钮，通过后端取消标记在当前视频处理完后中止后续补全。
- 将后端返回的 JSON 数据渲染到表格。

不应放入：
- CSV 解析逻辑。
- SQLite 连接逻辑。
- 文件名清洗规则。
- 文件重命名规则。

### `db_viewer.py`

数据库查看窗口。

职责：
- 展示已写入 SQLite 台账的视频记录。
- 搜索框变化时通过后端查询数据。
- 渲染后端返回的数据库记录。

不应放入：
- 直接 `sqlite3.connect(...)`。
- 数据库表结构定义。
- 数据写入逻辑。

### `actor_viewer.py`

作者库查看窗口。

职责：
- 展示已经识别并写入 `actors` 表的作者记录。
- 展示作者的主角、生日、年龄和匹配状态。
- 搜索框变化时通过后端查询作者库。

不应放入：
- 演员拆分规则。
- 演员统计 CSV 读取逻辑。
- SQLite 连接逻辑。

### `enrichment_dialog.py`

补全信息设置对话框。

职责：
- 让用户输入本次补全的视频数量。
- 提供“显示浏览器窗口”复选框，用于调试 Playwright 抓取流程。
- 提供“冷却 3 分钟后再搜索”复选框，用于进入 AVFan 页面后延迟搜索第一个编号。
- 将设置返回给 `Local_Video_gui.py`，再由 GUI 发送给后端。

### `path_library_viewer.py`

路径库查看与选择窗口。

职责：
- 展示保存在数据库中的本地视频路径。
- 以 U 盘入口风格显示路径状态。
- 展示路径对应存储卷的总容量、空闲空间、已用空间和使用率。
- U 盘拔出后，继续显示最后一次成功检测到的容量快照，并标记为未连接。
- 表格末尾追加合计行，汇总所有路径的总空间、总空闲、总占用和总占用比。
- 提供添加、删除、刷新和使用选中路径的按钮。
- 添加路径时通过文件夹选择器获得路径。
- 使用选中路径后，将路径返回给主界面作为当前扫描目录。

不应放入：
- 数据库写入 SQL。
- 路径规范化和存在性校验规则。

### `backend_client.py`

GUI 使用的 HTTP 客户端。

职责：
- 封装 `requests.get/post`。
- 提供语义化方法，例如 `scan_folder()`、`execute_renames()`、`save_plans()`、`list_videos()`。
- 将 HTTP 错误转换成 Python 异常，方便 GUI 弹窗展示。

这是前端与后端之间的唯一通信入口。

### `backend_server.py`

本地 HTTP 服务入口。

职责：
- 创建 `ThreadingHTTPServer`。
- 定义 JSON 请求读取和 JSON 响应输出。
- 将 URL 路由转发给 `BackendService`。
- 提供命令行启动入口。

主要接口：
- `GET /health`

## 2026-05 当前目录结构

重构后，项目代码统一收拢到 `app/` 目录下，根目录只保留启动入口、文档、配置模板和本地数据：

```text
Local-Video-Renamer/
├─ Local_Video_gui.py          # GUI 启动入口包装器
├─ backend_server.py           # 后端启动入口包装器
├─ ARCHITECTURE.md
├─ .env.example
├─ app/
│  ├─ api/
│  │  └─ video_renamer_api.py
│  ├─ backend/
│  │  ├─ client.py
│  │  ├─ server.py
│  │  └─ service.py
│  ├─ core/
│  │  ├─ app_config.py
│  │  ├─ filename_rules.py
│  │  ├─ project_paths.py
│  │  └─ video_models.py
│  ├─ data/
│  │  ├─ csv_video_loader.py
│  │  └─ database_handler.py
│  ├─ gui/
│  │  ├─ main_window.py
│  │  ├─ db_viewer.py
│  │  ├─ actor_viewer.py
│  │  ├─ path_library_viewer.py
│  │  └─ enrichment_dialog.py
│  ├─ scraper/
│  │  ├─ avfan_scraper.py
│  │  └─ login_status_service.py
│  └─ services/
│     ├─ actor_identifier.py
│     ├─ auto_login_service.py
│     ├─ path_library.py
│     └─ video_enrichment.py
├─ browser_profiles/           # 本地网页登录状态，不提交
├─ video_database.db           # 本地数据库，不提交
├─ 目录统计 - 详细介绍.csv       # 本地 CSV，不提交
└─ 目录统计 - 演员统计.csv       # 本地 CSV，不提交
```

目录分工：

- `app/core`：基础配置、公共路径、规则、数据模型
- `app/data`：CSV 和 SQLite 的底层读写
- `app/services`：作者识别、路径库、补全等业务服务
- `app/scraper`：AVFan 页面抓取与登录状态检测
- `app/backend`：本地 HTTP 后端
- `app/gui`：PyQt 界面层
- `app/api`：视频扫描、命名、重命名的聚合业务接口

## 2026-05 一键启动

为了不依赖 PyCharm 手动运行脚本，项目根目录新增了两个启动入口：

- `启动系统.bat`
  - 可直接双击启动系统
  - 内部会调用 `start_vidnorm.ps1`
  - 会优先读取本地 `.env` 中的 `APP_PYTHON_EXE`
  - 若未配置，则自动尝试 `.venv`、`venv`、`pyw.exe`、`py.exe`、`pythonw.exe`、`python.exe`
- `启动系统_静默.vbs`
  - 静默调用 `启动系统.bat`
  - 适合像普通桌面程序一样点击启动

相关文件：

- [启动系统.bat](D:/pycharm_pro/Local-Video-Renamer/启动系统.bat)
- [启动系统_静默.vbs](D:/pycharm_pro/Local-Video-Renamer/启动系统_静默.vbs)
- [start_vidnorm.ps1](D:/pycharm_pro/Local-Video-Renamer/start_vidnorm.ps1)
- `POST /database/reload`
- `POST /scan`
- `POST /rename`
- `POST /database/save`
- `GET /database/videos?q=关键词`
- `GET /database/actors?q=关键词`
- `GET /paths`
- `POST /paths/add`
- `POST /paths/delete`
- `POST /database/enrich`
- `POST /browser-profile/reset`
- `POST /login/auto`

不应放入：
- 文件名清洗规则。
- CSV 读取规则。
- SQLite SQL 细节。
- 复杂业务流程。

### `backend_service.py`

后端业务协调层。

职责：
- 管理 CSV 路径和 SQLite 路径。
- 持有 `VideoRenamerAPI` 和 `VideoDatabase`。
- 实现后端接口对应的业务动作：
  - 加载 CSV 数据库。
  - 扫描文件夹。
  - 执行重命名。
- 保存扫描结果到 SQLite。
- 查询 SQLite 台账。
- 识别扫描结果中的单个作者并写入作者表。
  - 查询作者库。
  - 添加、删除和查询路径库。
  - 打开网页登录页并自动填入本地账号密码。
  - 批量补全未补全视频的 AVFan 详情信息。
- 将业务对象转换为 JSON 可返回的数据。

如果要新增一个后端业务接口，通常先从这里加方法，再到 `backend_server.py` 增加路由。

### `auto_login_service.py`

网页登录辅助模块。

职责：
- 从 `.env` 读取登录链接、账号和密码。
- 使用 Playwright 打开登录页。
- 自动填入账号密码。
- 等待用户手动完成图片验证码并点击登录。
- 登录成功后复用同一套 `browser_profiles/avfan` 登录状态。

### `app_config.py`

本地配置读取模块。

职责：
- 读取项目根目录的 `.env`。
- 提供 `get_setting()` 给业务模块读取本地配置。
- 将访问网页这类个人配置从主程序代码中剥离出去。

### `video_renamer_api.py`

视频规范化业务 API。

职责：
- 加载 CSV 视频元数据。
- 递归扫描本地文件夹。
- 根据文件名提取编号。
- 根据编号匹配元数据。
- 生成 `RenamePlan`。
- 执行物理文件重命名。

注意：
- 此模块是业务协调器，不应该继续塞入数据模型、CSV 解析细节、文件名规则。
- 这些细节已经拆到 `video_models.py`、`csv_video_loader.py`、`filename_rules.py`。

### `video_models.py`

业务数据模型和 JSON 转换。

职责：
- 定义 `VideoMetadata`。
- 定义 `RenamePlan`。
- 定义 `RenameResult`。
- `RenamePlan.storage_location` 保存扫描入口名称，例如 `2号U盘`。
- 提供模型与 `dict` 的转换函数：
  - `metadata_to_dict()`
  - `metadata_from_dict()`
  - `plan_to_dict()`
  - `plan_from_dict()`
  - `result_to_dict()`

如果后端和 GUI 之间要传递新的字段，优先改这里。

### `actor_identifier.py`

作者识别与演员统计 CSV 关联模块。

职责：
- 从视频作者字符串中拆分单个作者。
- 支持空格、逗号、顿号、斜杠等常见分隔符。
- `无`、`暂无`、`未知` 等占位值表示没有演员信息，会被过滤掉。
- 加载 `目录统计 - 演员统计.csv`。
- 用 CSV 中的 `主角` 字段建立作者索引。
- 将识别出的作者与 `生日`、`年龄` 信息关联。

示例：

```text
浅井心晴 新村あかり
```

会被识别为：

```text
浅井心晴
新村あかり
```

### `path_library.py`

路径库业务规则模块。

职责：
- 规范化用户选择的本地文件夹路径。
- 保留用户选择的挂载入口路径显示，例如 `D:\视频库连接入口\2号U盘`，不解析成底层盘符路径。
- 从扫描入口路径提取存放位置名称，例如 `D:\视频库连接入口\2号U盘` 提取为 `2号U盘`。
- 校验路径是否存在且是否为文件夹。
- 给数据库路径记录补充当前是否可用的状态。
- 检测路径所在存储卷的容量、空闲空间、已用空间和使用率。
- 在 Windows 上尽量识别卷类型，例如 U 盘/可移动盘、本地磁盘等。
- 在线时刷新容量快照；离线时返回数据库保存的最后一次容量快照。

路径库只保存本地路径文本，不复制或移动视频文件。

### `avfan_scraper.py`

AVFan 网页抓取模块。

职责：
- 从 `.env` 读取 `SCRAPER_HOME_URL`，不在主程序中硬编码目标网页。
- 使用 Playwright 打开 AVFan 首页。
- 优先使用系统 Google Chrome 启动持久化上下文；如果不可用，则回退到 Playwright Chromium。
- 根据补全设置决定是否显示浏览器窗口；默认后台运行，勾选后使用可见浏览器运行。
- 使用 `browser_profiles/avfan` 作为 Playwright 专用持久化登录档案，复用登录 Cookie 和本地存储。
- 批量补全时复用同一个浏览器会话与页面，优先在当前详情页直接搜索下一个编号，而不是每个视频重新打开浏览器。
- 如果遇到 Cloudflare 真人验证，可见浏览器模式会等待用户手动完成；后台模式会提示用户重新勾选“显示浏览器窗口”。
- 如果后台运行时遇到登录页，会提示用户勾选“显示浏览器窗口”并完成登录。
- 可选启用首次搜索前 3 分钟冷却；冷却只在本次批量补全的第一个搜索前执行一次。
- 提供重置函数清理 `browser_profiles/avfan`，用于验证状态或 Cookie 卡死时重新建立网页登录环境。
- 处理成年确认弹窗。
- 在首页搜索框输入视频编号并点击搜索。
- 打开搜索结果详情页。
- 解析 `视频ID`、`发行日期`、`制作商`、`发行商` 等详情字段。

不应放入：
- 数据库写入逻辑。
- GUI 弹窗逻辑。
- 批量补全调度逻辑。

### `video_enrichment.py`

视频信息补全业务模块。

职责：
- 从数据库读取指定数量的未补全视频。
- 根据 `show_browser` 和 `cooldown_before_search` 创建 `AvfanScraper`。
- 逐个调用 `AvfanScraper` 根据视频编号补全信息，并在同一浏览器页面中连续搜索后续编号。
- 将成功结果写回数据库并标记为 `已补全`。
- 将失败结果标记为 `补全失败`，保留错误信息。

### `filename_rules.py`

文件名解析、清洗和生成规则。

职责：
- 定义支持的视频后缀。
- 清除标题首尾噪声字符。
- 清除标题末尾混入的 `.mp4`、`。.mp4`、`mp4。` 等异常尾巴。
- 压缩多余空白。
- 从文件名提取编号，例如 `CMV-001`、`CMV_001`、`CMV 001`、`CMV001`。
- 生成最终规范文件名。

当前规范命名格式：

```text
【编号】-标题-{作者}.mp4
```

如果作者为空，则生成：

```text
【编号】-标题.mp4
```

### `csv_video_loader.py`

CSV 元数据加载模块。

职责：
- 读取个人 CSV 数据文件。
- 从 CSV 行中提取：
  - `系列名称`
  - `名称`
  - `演员`
  - `时长(可读)`
  - `大小(GB)`
- 调用 `filename_rules.clean_video_title()` 清洗标题。
- 返回以视频编号为 key 的元数据字典。

CSV 是个人数据，不应提交到 Git。

### `database_handler.py`

SQLite 台账访问模块。

职责：
- 初始化 `processed_videos` 表。
- 初始化 `actors` 表。
- 初始化 `path_library` 表。
- 批量保存扫描结果。
- 保存 AVFan 补全字段：`视频ID`、`发行日期`、`制作商`、`发行商`、`补全状态`。
- 批量保存识别出的作者。
- 查询已保存的视频台账。
- 查询已保存的作者库。
- 添加、删除和查询路径库。

这是系统唯一的数据库模块。不要恢复或新增功能重复的 `database.py`。

## 数据流

### 启动流程

```text
Local_Video_gui.py
  -> BackendClient.health()
  -> 如果后端未启动，则 subprocess 启动 backend_server.py
  -> BackendClient.reload_database()
  -> backend_service.load_database()
  -> csv_video_loader.load_video_database()
```

### 扫描流程

```text
用户选择文件夹
  -> 点击“扫描并匹配 CSV”
  -> Local_Video_gui.scan_files()
  -> BackendClient.scan_folder(folder_path)
  -> POST /scan
  -> BackendService.scan()
  -> VideoRenamerAPI.scan_folder()
  -> 返回 plans JSON
  -> GUI 渲染表格
```

### 写入数据库流程

```text
用户点击“写入数据库”
  -> BackendClient.save_plans(plans)
  -> POST /database/save
  -> BackendService.save_plans()
  -> VideoDatabase.save_plans()
  -> 将 RenamePlan.storage_location 写入 processed_videos.storage_location
  -> ActorIdentifier.identify_from_plans()
  -> VideoDatabase.save_actors()
  -> SQLite REPLACE INTO processed_videos
  -> SQLite REPLACE INTO actors
```

### 重命名流程

```text
用户点击“执行重命名”
  -> BackendClient.execute_renames(plans)
  -> POST /rename
  -> BackendService.rename()
  -> VideoRenamerAPI.execute_renames()
  -> 本地文件系统 rename
  -> 返回 results JSON
  -> GUI 更新状态列
```

### 查看数据库流程

```text
用户点击“查看数据库”
  -> DatabaseViewerWindow
  -> BackendClient.list_videos(search_text)
  -> GET /database/videos
  -> BackendService.list_videos()
  -> VideoDatabase.list_videos()
  -> GUI 表格渲染记录
```

### 查看作者库流程

```text
用户点击“查看作者库”
  -> ActorViewerWindow
  -> BackendClient.list_actors(search_text)
  -> GET /database/actors
  -> BackendService.list_actors()
  -> VideoDatabase.list_actors()
  -> GUI 表格渲染作者、生日、年龄
```

### 路径库流程

```text
用户点击“路径库”
  -> PathLibraryWindow
  -> BackendClient.list_paths()
  -> GET /paths
  -> BackendService.list_paths()
  -> VideoDatabase.list_paths()
  -> GUI 表格渲染已保存路径

用户点击“添加”
  -> QFileDialog 选择文件夹
  -> BackendClient.add_path(folder_path)
  -> POST /paths/add
  -> PathLibrary.build_path_record()
  -> VideoDatabase.add_path()

用户点击“删除”
  -> BackendClient.delete_path(path_id)
  -> POST /paths/delete
  -> VideoDatabase.delete_path()

用户点击“使用选中路径”
  -> PathLibraryWindow.selected_path
  -> Local_Video_gui.set_current_folder()
```

### 补全信息流程

```text
用户点击“补全信息”
  -> EnrichmentDialog 输入本次补全数量
  -> 可选勾选“显示浏览器窗口”
  -> 可选勾选“冷却 3 分钟后再搜索”
  -> BackendClient.enrich_videos(limit, show_browser, cooldown_before_search)
  -> POST /database/enrich
  -> BackendService.enrich_videos(limit, show_browser, cooldown_before_search)
  -> VideoEnrichmentService(show_browser=show_browser, cooldown_before_search=cooldown_before_search).enrich_next_videos()
  -> VideoDatabase.list_videos_for_enrichment(limit)
  -> AvfanScraper.fetch_by_code(code)
  -> VideoDatabase.update_video_enrichment()
  -> processed_videos 标记为“已补全”或“补全失败”
```

### 重置网页登录流程

```text
用户点击“重置网页登录”
  -> GUI 弹出确认框
  -> BackendClient.reset_browser_profile()
  -> POST /browser-profile/reset
  -> BackendService.reset_browser_profile()
  -> reset_avfan_browser_profile()
  -> 删除 browser_profiles/avfan
```

### 自动登录流程

```text
用户点击“自动登录”
  -> GUI 后台线程启动 AutoLoginWorker
  -> BackendClient.auto_login()
  -> POST /login/auto
  -> BackendService.auto_login()
  -> AutoLoginService.run()
  -> 打开登录链接并自动填入账号密码
  -> 用户手动输入图片验证码并点击登录
  -> 登录成功后复用 browser_profiles/avfan
```

## 本地个人数据

以下文件类型属于个人本地数据，已经在 `.gitignore` 中忽略：

```gitignore
*.csv
*.db
.env
browser_profiles/
```

注意：
- `.gitignore` 只阻止未来未跟踪文件进入 Git。
- 如果某个 `.csv` 或 `.db` 曾经已经被 Git 跟踪，需要使用 `git rm --cached` 从索引移除。
- `.env` 中保存的是本机网页访问配置，仓库中只保留 `.env.example` 作为模板。
- `browser_profiles/` 中可能保存网页登录状态、Cookie、LocalStorage 等敏感信息，只允许本机使用。
- 如果个人数据已经推送到远程历史，普通删除只能移除最新版本，历史记录仍可能保留，需要单独做历史清理。

## 推荐修改位置

新增或修改文件名规则：

```text
filename_rules.py
```

新增 CSV 字段映射：

```text
csv_video_loader.py
video_models.py
```

新增或修改作者识别规则：

```text
actor_identifier.py
database_handler.py
```

新增或修改路径库业务：

```text
path_library.py
database_handler.py
```

新增或修改网页补全业务：

```text
avfan_scraper.py
video_enrichment.py
database_handler.py
```

新增后端接口：

```text
backend_service.py
backend_server.py
backend_client.py
```

新增 GUI 按钮或界面交互：

```text
Local_Video_gui.py
```

新增数据库字段或查询：

```text
database_handler.py
video_models.py
```

修改数据库查看窗口：

```text
db_viewer.py
```

修改作者库查看窗口：

```text
actor_viewer.py
```

修改路径库查看窗口：

```text
path_library_viewer.py
```

## 不建议的改法

- 不要在 GUI 里直接 `sqlite3.connect()`。
- 不要在 GUI 里直接读取 CSV。
- 不要在 `backend_server.py` 里写复杂业务逻辑。
- 不要重新创建 `database.py`，数据库功能统一放在 `database_handler.py`。
- 不要提交 `.csv` 或 `.db` 文件。
- 不要提交 `.env`，只提交 `.env.example`。
- 不要提交 `browser_profiles/`。
- 不要在多个模块里复制文件名清洗正则，统一使用 `filename_rules.py`。
- 不要在 GUI 或作者库页面里拆分作者字符串，统一使用 `actor_identifier.py`。
- 不要在路径库页面里直接写 SQL，统一通过后端和 `path_library.py`。
- 不要恢复 `playwright_avfan_demo.py` 或 `playwright_avfan_search_demo.py`，正式抓取统一使用 `avfan_scraper.py`。

## 快速验证命令

编译检查：

```powershell
python -m py_compile .\Local_Video_gui.py .\actor_identifier.py .\actor_viewer.py .\app_config.py .\auto_login_service.py .\avfan_scraper.py .\backend_client.py .\backend_server.py .\backend_service.py .\csv_video_loader.py .\database_handler.py .\db_viewer.py .\enrichment_dialog.py .\filename_rules.py .\login_status_service.py .\path_library.py .\path_library_viewer.py .\video_enrichment.py .\video_models.py .\video_renamer_api.py
```

后端手动启动：

```powershell
python .\backend_server.py
```

启动后可访问：

```text
http://127.0.0.1:8766/health
```

## 当前模块清单

```text
Local_Video_gui.py      GUI 主窗口
db_viewer.py            数据库查看窗口
actor_viewer.py         作者库查看窗口
enrichment_dialog.py    补全信息设置对话框
path_library_viewer.py  路径库查看与选择窗口
backend_client.py       GUI 到后端的 HTTP 客户端
backend_server.py       本地 HTTP 服务入口和路由
backend_service.py      后端业务协调层
video_renamer_api.py    视频扫描与重命名业务 API
video_models.py         业务数据模型与 JSON 转换
filename_rules.py       文件名规则与标题清洗
csv_video_loader.py     CSV 元数据加载
actor_identifier.py     作者识别与演员统计 CSV 关联
path_library.py         路径库业务规则
avfan_scraper.py        AVFan Playwright 网页抓取
video_enrichment.py     视频信息批量补全业务
database_handler.py     SQLite 台账访问
```
