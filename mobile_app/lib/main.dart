import 'package:flutter/material.dart';

import 'src/database/database_status.dart';
import 'src/database/database_storage.dart';
import 'src/ui/app_shell.dart';

void main() {
  runApp(const LocalVideoApp());
}

class LocalVideoApp extends StatelessWidget {
  const LocalVideoApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF8E3B2E);
    return MaterialApp(
      title: '私人视频库图鉴',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: seed,
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF5EFE7),
        cardTheme: const CardThemeData(
          color: Colors.white,
          elevation: 0,
          margin: EdgeInsets.zero,
        ),
      ),
      home: const DatabaseBootstrapScreen(),
    );
  }
}

class DatabaseBootstrapScreen extends StatefulWidget {
  const DatabaseBootstrapScreen({super.key});

  @override
  State<DatabaseBootstrapScreen> createState() => _DatabaseBootstrapScreenState();
}

class _DatabaseBootstrapScreenState extends State<DatabaseBootstrapScreen> {
  final DatabaseStorage _storage = const DatabaseStorage();
  late Future<DatabaseStatus> _statusFuture;

  @override
  void initState() {
    super.initState();
    _statusFuture = _storage.inspectStatus();
  }

  void _reloadStatus() {
    setState(() {
      _statusFuture = _storage.inspectStatus();
    });
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<DatabaseStatus>(
      future: _statusFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const _LoadingScreen();
        }
        if (snapshot.hasError) {
          return _DatabaseErrorScreen(
            message: snapshot.error.toString(),
            onRetry: _reloadStatus,
          );
        }

        final status = snapshot.data!;
        if (status.exists) {
          return AppShell(
            databaseStatus: status,
            onRefreshDatabaseStatus: _reloadStatus,
          );
        }

        return DatabaseMissingScreen(
          status: status,
          onRetry: _reloadStatus,
        );
      },
    );
  }
}

class _LoadingScreen extends StatelessWidget {
  const _LoadingScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF2A211F), Color(0xFF6C463A), Color(0xFFF5EFE7)],
          ),
        ),
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(height: 16),
              Text(
                '正在检查本地数据库...',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DatabaseErrorScreen extends StatelessWidget {
  const _DatabaseErrorScreen({
    required this.message,
    required this.onRetry,
  });

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '数据库检查失败',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 12),
                    Text(message),
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: onRetry,
                      child: const Text('重新检查'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class DatabaseMissingScreen extends StatelessWidget {
  const DatabaseMissingScreen({
    super.key,
    required this.status,
    required this.onRetry,
  });

  final DatabaseStatus status;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF2A211F), Color(0xFF734738), Color(0xFFF5EFE7)],
          ),
        ),
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: 16),
                    Text(
                      '私人视频库图鉴',
                      style: theme.textTheme.displaySmall?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '当前还没有检测到 video_database.db。把数据库手动复制到下方目录后，点击“重新检查”即可进入 App。',
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.92),
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 24),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _MetaLine(label: '检测位置', value: status.directoryLabel),
                            const SizedBox(height: 12),
                            _MetaLine(label: '目标文件', value: status.databasePath),
                            const SizedBox(height: 12),
                            _MetaLine(label: '文件名', value: DatabaseStorage.databaseFileName),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '手动放置步骤',
                              style: theme.textTheme.titleLarge?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 12),
                            const Text('1. 用数据线或文件管理器打开手机对应目录。'),
                            const SizedBox(height: 8),
                            const Text('2. 将 PC 端生成的 video_database.db 复制到上方目标路径。'),
                            const SizedBox(height: 8),
                            const Text('3. 回到 App，点击“重新检查”。'),
                            const SizedBox(height: 8),
                            const Text('4. 如果 Android 文件管理器看不到该目录，优先使用 USB 连接电脑复制。'),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    Row(
                      children: [
                        FilledButton.icon(
                          onPressed: onRetry,
                          icon: const Icon(Icons.refresh),
                          label: const Text('重新检查'),
                        ),
                        const SizedBox(width: 12),
                        OutlinedButton.icon(
                          onPressed: onRetry,
                          icon: const Icon(Icons.folder_open),
                          label: const Text('我已经复制好了'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 18),
                    Text(
                      '当前版本先实现“数据库存在即可进入”的只读壳层。下一步可以直接接入 SQLite 查询和三大列表页面。',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: Colors.white.withValues(alpha: 0.88),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _MetaLine extends StatelessWidget {
  const _MetaLine({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: theme.textTheme.labelLarge?.copyWith(
            color: const Color(0xFF8E3B2E),
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 4),
        SelectableText(
          value,
          style: theme.textTheme.bodyMedium?.copyWith(
            fontFamily: 'monospace',
            height: 1.45,
          ),
        ),
      ],
    );
  }
}
