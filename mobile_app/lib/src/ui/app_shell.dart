import 'package:flutter/material.dart';

import '../database/database_status.dart';
import 'video_library_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.databaseStatus,
    required this.onRefreshDatabaseStatus,
  });

  final DatabaseStatus databaseStatus;
  final VoidCallback onRefreshDatabaseStatus;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _currentIndex = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_titleForIndex(_currentIndex)),
        actions: [
          IconButton(
            tooltip: '数据库状态',
            onPressed: () => _showDatabaseSheet(context),
            icon: const Icon(Icons.storage_rounded),
          ),
        ],
      ),
      body: IndexedStack(
        index: _currentIndex,
        children: [
          VideoLibraryScreen(
            databaseStatus: widget.databaseStatus,
            onRefreshDatabaseStatus: widget.onRefreshDatabaseStatus,
          ),
          _ComingSoonScreen(
            icon: Icons.people_alt_rounded,
            title: '演员库',
            description: '下一步会接入演员网格、作品数量统计和演员档案页。',
          ),
          _ComingSoonScreen(
            icon: Icons.grid_view_rounded,
            title: '系列库',
            description: '下一步会接入前缀分组、系列统计和系列详情页。',
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.video_library_outlined),
            selectedIcon: Icon(Icons.video_library_rounded),
            label: '视频库',
          ),
          NavigationDestination(
            icon: Icon(Icons.people_alt_outlined),
            selectedIcon: Icon(Icons.people_alt_rounded),
            label: '演员库',
          ),
          NavigationDestination(
            icon: Icon(Icons.grid_view_outlined),
            selectedIcon: Icon(Icons.grid_view_rounded),
            label: '系列库',
          ),
        ],
      ),
    );
  }

  String _titleForIndex(int index) {
    switch (index) {
      case 1:
        return '演员库';
      case 2:
        return '系列库';
      case 0:
      default:
        return '视频库';
    }
  }

  Future<void> _showDatabaseSheet(BuildContext context) {
    final theme = Theme.of(context);
    return showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '数据库状态',
                style: theme.textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 16),
              _StatusRow(label: '状态', value: widget.databaseStatus.exists ? '已检测到' : '未检测到'),
              _StatusRow(label: '位置', value: widget.databaseStatus.directoryLabel),
              _StatusRow(label: '文件大小', value: widget.databaseStatus.sizeLabel),
              _StatusRow(label: '最后修改', value: widget.databaseStatus.modifiedLabel),
              const SizedBox(height: 12),
              SelectableText(widget.databaseStatus.databasePath),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: () {
                  Navigator.of(context).pop();
                  widget.onRefreshDatabaseStatus();
                },
                icon: const Icon(Icons.refresh),
                label: const Text('重新检查数据库'),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _ComingSoonScreen extends StatelessWidget {
  const _ComingSoonScreen({
    required this.icon,
    required this.title,
    required this.description,
  });

  final IconData icon;
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(28),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [Color(0xFF2A211F), Color(0xFF734738)],
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: Colors.white, size: 34),
              const SizedBox(height: 20),
              Text(
                title,
                style: theme.textTheme.headlineMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 10),
              Text(
                description,
                style: theme.textTheme.bodyLarge?.copyWith(
                  color: Colors.white.withValues(alpha: 0.9),
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '当前状态',
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 12),
                const Text('视频库已经开始直接读取 SQLite。'),
                const SizedBox(height: 8),
                const Text('这个页面的查询与详情链路将在下一轮接上。'),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 88,
            child: Text(
              label,
              style: theme.textTheme.labelLarge?.copyWith(
                color: const Color(0xFF8E3B2E),
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Expanded(
            child: Text(value),
          ),
        ],
      ),
    );
  }
}
