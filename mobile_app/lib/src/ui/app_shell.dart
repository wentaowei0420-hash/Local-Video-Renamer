import 'package:flutter/material.dart';

import '../database/database_status.dart';
import 'actor_library_screen.dart';
import 'code_prefix_library_screen.dart';
import 'theme/app_design.dart';
import 'theme/app_icons.dart';
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
            icon: const Icon(LucideIcons.database, size: 20),
          ),
        ],
      ),
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: AppDesign.appBackground,
        ),
        child: IndexedStack(
          index: _currentIndex,
          children: [
            VideoLibraryScreen(
              databaseStatus: widget.databaseStatus,
              onRefreshDatabaseStatus: widget.onRefreshDatabaseStatus,
            ),
            ActorLibraryScreen(
              databaseStatus: widget.databaseStatus,
              onRefreshDatabaseStatus: widget.onRefreshDatabaseStatus,
            ),
            CodePrefixLibraryScreen(
              databaseStatus: widget.databaseStatus,
              onRefreshDatabaseStatus: widget.onRefreshDatabaseStatus,
            ),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: AppDesign.surface.withValues(alpha: 0.96),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: AppDesign.border),
            boxShadow: AppDesign.softShadow,
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(28),
            child: NavigationBar(
              height: 72,
              selectedIndex: _currentIndex,
              onDestinationSelected: (index) {
                setState(() {
                  _currentIndex = index;
                });
              },
              destinations: const [
                NavigationDestination(
                  icon: Icon(LucideIcons.video, size: 20),
                  selectedIcon: Icon(LucideIcons.videotape, size: 20),
                  label: '视频库',
                ),
                NavigationDestination(
                  icon: Icon(LucideIcons.user2, size: 20),
                  selectedIcon: Icon(LucideIcons.users, size: 20),
                  label: '演员库',
                ),
                NavigationDestination(
                  icon: Icon(LucideIcons.grid, size: 20),
                  selectedIcon: Icon(LucideIcons.layoutGrid, size: 20),
                  label: '番号库',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  String _titleForIndex(int index) {
    switch (index) {
      case 1:
        return '演员库';
      case 2:
        return '番号库';
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
      backgroundColor: AppDesign.surface,
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
                icon: const Icon(LucideIcons.refreshCw, size: 18),
                label: const Text('重新检查数据库'),
              ),
            ],
          ),
        );
      },
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
                color: AppDesign.indigo,
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
