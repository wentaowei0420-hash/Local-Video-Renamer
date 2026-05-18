# Local Video Renamer 系统结构说明

本文档用于帮助开发者或 AI 快速理解项目结构、模块职责和数据流。修改代码前请先阅读本文件，优先保持现有分层，不要把业务逻辑重新堆回 GUI 或 HTTP 路由文件里。

## 一句话概览

这是一个本地视频规范化工具：PyQt GUI 只负责界面和按钮交互，所有扫描、匹配、重命名、CSV 读取、SQLite 台账操作都通过本地 HTTP 后端完成。

```text
PyQt GUI
  -> backend_client.py
  -> http://127.0.0.1:8765
  -> backend_server.py
  -> backend_service.py
  -> video_renamer_api.py / actor_identifier.py / path_library.py / database_handler.py
  -> CSV / SQLite DB / 本地文件系统
```

## 核心设计原则

- GUI 不直接读取 CSV、SQLite，也不直接执行重命名业务。
- HTTP 路由层只负责解析请求和返回 JSON，不写业务规则。
- 业务协调层负责组织扫描、重命名、数据库保存等流程。
- 独立规则放独立模块，例如文件名清洗、CSV 加载、数据模型。
- 演员识别独立放在 `actor_identifier.py`，不要混进 GUI 或数据库查询页面。
- 路径库业务独立放在 `path_library.py`，GUI 只负责展示、添加、删除和选择。
- `.csv` 和 `.db` 是个人本地数据，不应提交到 Git。

## 模块职责

### `Local_Video_gui.py`

PyQt 主界面入口。

职责：
- 创建主窗口、按钮、路径输入框和扫描结果表格。
- 启动时检查本地后端是否可用，不可用则自动拉起 `backend_server.py`。
- 用户点击按钮后，通过 `BackendClient` 调用后端接口。
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

### `path_library_viewer.py`

路径库查看与选择窗口。

职责：
- 展示保存在数据库中的本地视频路径。
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
- `POST /database/reload`
- `POST /scan`
- `POST /rename`
- `POST /database/save`
- `GET /database/videos?q=关键词`
- `GET /database/actors?q=关键词`
- `GET /paths`
- `POST /paths/add`
- `POST /paths/delete`

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
- 将业务对象转换为 JSON 可返回的数据。

如果要新增一个后端业务接口，通常先从这里加方法，再到 `backend_server.py` 增加路由。

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
- 校验路径是否存在且是否为文件夹。
- 给数据库路径记录补充当前是否可用的状态。

路径库只保存本地路径文本，不复制或移动视频文件。

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

## 本地个人数据

以下文件类型属于个人本地数据，已经在 `.gitignore` 中忽略：

```gitignore
*.csv
*.db
```

注意：
- `.gitignore` 只阻止未来未跟踪文件进入 Git。
- 如果某个 `.csv` 或 `.db` 曾经已经被 Git 跟踪，需要使用 `git rm --cached` 从索引移除。
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
- 不要在多个模块里复制文件名清洗正则，统一使用 `filename_rules.py`。
- 不要在 GUI 或作者库页面里拆分作者字符串，统一使用 `actor_identifier.py`。
- 不要在路径库页面里直接写 SQL，统一通过后端和 `path_library.py`。

## 快速验证命令

编译检查：

```powershell
python -m py_compile .\Local_Video_gui.py .\actor_identifier.py .\actor_viewer.py .\backend_client.py .\backend_server.py .\backend_service.py .\csv_video_loader.py .\database_handler.py .\db_viewer.py .\filename_rules.py .\path_library.py .\path_library_viewer.py .\video_models.py .\video_renamer_api.py
```

后端手动启动：

```powershell
python .\backend_server.py
```

启动后可访问：

```text
http://127.0.0.1:8765/health
```

## 当前模块清单

```text
Local_Video_gui.py      GUI 主窗口
db_viewer.py            数据库查看窗口
actor_viewer.py         作者库查看窗口
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
database_handler.py     SQLite 台账访问
```
