import 'dart:async';

import 'package:flutter/material.dart';

import '../database/database_status.dart';
import '../database/video_library_repository.dart';
import '../database/video_list_item.dart';
import '../database/video_search_result.dart';

class VideoLibraryScreen extends StatefulWidget {
  const VideoLibraryScreen({
    super.key,
    required this.databaseStatus,
    required this.onRefreshDatabaseStatus,
  });

  final DatabaseStatus databaseStatus;
  final VoidCallback onRefreshDatabaseStatus;

  @override
  State<VideoLibraryScreen> createState() => _VideoLibraryScreenState();
}

class _VideoLibraryScreenState extends State<VideoLibraryScreen> {
  late final VideoLibraryRepository _repository;
  final TextEditingController _searchController = TextEditingController();
  Timer? _searchDebounce;
  late Future<VideoSearchResult> _resultFuture;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _repository = VideoLibraryRepository(
      databasePath: widget.databaseStatus.databasePath,
    );
    _resultFuture = _repository.searchVideos();
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    unawaited(_repository.dispose());
    super.dispose();
  }

  Future<void> _reload() async {
    widget.onRefreshDatabaseStatus();
    setState(() {
      _resultFuture = _repository.searchVideos(query: _query);
    });
    await _resultFuture;
  }

  void _handleSearchChanged(String value) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 280), () {
      if (!mounted) {
        return;
      }
      final normalized = value.trim();
      if (normalized == _query) {
        return;
      }
      setState(() {
        _query = normalized;
        _resultFuture = _repository.searchVideos(query: _query);
      });
    });
  }

  void _clearSearch() {
    _searchDebounce?.cancel();
    _searchController.clear();
    if (_query.isEmpty) {
      return;
    }
    setState(() {
      _query = '';
      _resultFuture = _repository.searchVideos();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
        children: [
          Container(
            padding: const EdgeInsets.all(22),
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
                Text(
                  '本地视频库',
                  style: theme.textTheme.headlineMedium?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  '直接读取 video_database.db 的 processed_videos。先完成编号搜索与只读卡片列表。',
                  style: theme.textTheme.bodyLarge?.copyWith(
                    color: Colors.white.withValues(alpha: 0.9),
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 18),
                TextField(
                  controller: _searchController,
                  onChanged: _handleSearchChanged,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: '搜索番号、标题、演员、存储位置',
                    prefixIcon: const Icon(Icons.search),
                    suffixIcon: _query.isEmpty
                        ? null
                        : IconButton(
                            onPressed: _clearSearch,
                            icon: const Icon(Icons.close),
                          ),
                    filled: true,
                    fillColor: Colors.white,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(20),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Wrap(
                runSpacing: 10,
                spacing: 10,
                children: [
                  _InfoChip(
                    icon: Icons.storage_rounded,
                    label: '数据库已连接',
                    value: widget.databaseStatus.sizeLabel,
                  ),
                  _InfoChip(
                    icon: Icons.search_rounded,
                    label: '当前搜索',
                    value: _query.isEmpty ? '全部视频' : _query,
                  ),
                  _InfoChip(
                    icon: Icons.folder_open_rounded,
                    label: '存放位置',
                    value: widget.databaseStatus.directoryLabel,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          FutureBuilder<VideoSearchResult>(
            future: _resultFuture,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              if (snapshot.hasError) {
                return _VideoLoadError(
                  errorText: snapshot.error.toString(),
                  onRetry: () {
                    setState(() {
                      _resultFuture = _repository.searchVideos(query: _query);
                    });
                  },
                );
              }

              final result = snapshot.data!;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      result.hasMore
                          ? '共 ${result.totalCount} 条，当前展示前 ${result.items.length} 条'
                          : '共 ${result.totalCount} 条',
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  if (result.items.isEmpty)
                    const _EmptyVideoState()
                  else
                    for (final item in result.items) ...[
                      _VideoCard(item: item),
                      const SizedBox(height: 12),
                    ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({
    required this.icon,
    required this.label,
    required this.value,
  });

  final IconData icon;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF4ECE5),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 18, color: const Color(0xFF8E3B2E)),
          const SizedBox(width: 8),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                label,
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: const Color(0xFF8E3B2E),
                      fontWeight: FontWeight.w700,
                    ),
              ),
              const SizedBox(height: 2),
              Text(value),
            ],
          ),
        ],
      ),
    );
  }
}

class _VideoCard extends StatelessWidget {
  const _VideoCard({
    required this.item,
  });

  final VideoListItem item;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final metaValues = <String>[
      if (item.releaseDate.isNotEmpty) '日期 ${item.releaseDate}',
      if (item.duration.isNotEmpty) '时长 ${item.duration}',
      if (item.size.isNotEmpty) '大小 ${item.size}',
    ];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 10,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  item.code.isEmpty ? '未命名编号' : item.code,
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.6,
                  ),
                ),
                if (item.enrichmentStatus.isNotEmpty)
                  _Badge(
                    text: item.enrichmentStatus,
                    foreground: const Color(0xFF5A382F),
                    background: const Color(0xFFEAD8CC),
                  ),
                if (item.videoCategory.isNotEmpty)
                  _Badge(
                    text: item.videoCategory,
                    foreground: const Color(0xFF2D5F50),
                    background: const Color(0xFFDCEFE9),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              item.title.isEmpty ? item.code : item.title,
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w600,
                height: 1.35,
              ),
            ),
            if (item.author.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                item.author,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: const Color(0xFF5C5752),
                ),
              ),
            ],
            if (metaValues.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                metaValues.join('  ·  '),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF6A625C),
                ),
              ),
            ],
            if (item.storageLocation.isNotEmpty) ...[
              const SizedBox(height: 14),
              _DetailLine(
                label: '存储位置',
                value: item.storageLocation,
                highlight: true,
              ),
            ],
            if (item.maker.isNotEmpty) ...[
              const SizedBox(height: 8),
              _DetailLine(label: '制作商', value: item.maker),
            ],
            if (item.publisher.isNotEmpty) ...[
              const SizedBox(height: 8),
              _DetailLine(label: '发行商', value: item.publisher),
            ],
          ],
        ),
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  const _DetailLine({
    required this.label,
    required this.value,
    this.highlight = false,
  });

  final String label;
  final String value;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final valueColor = highlight ? const Color(0xFF8E3B2E) : const Color(0xFF3E3935);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 66,
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: const Color(0xFF8A7E75),
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: valueColor,
                  fontWeight: highlight ? FontWeight.w700 : FontWeight.w500,
                ),
          ),
        ),
      ],
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({
    required this.text,
    required this.foreground,
    required this.background,
  });

  final String text;
  final Color foreground;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: foreground,
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

class _EmptyVideoState extends StatelessWidget {
  const _EmptyVideoState();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            const Icon(Icons.search_off_rounded, size: 34),
            const SizedBox(height: 12),
            Text(
              '没有找到匹配的视频',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 8),
            const Text(
              '可以尝试输入完整番号、部分标题、演员名或存储位置关键字。',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

class _VideoLoadError extends StatelessWidget {
  const _VideoLoadError({
    required this.errorText,
    required this.onRetry,
  });

  final String errorText;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '视频库读取失败',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
            ),
            const SizedBox(height: 10),
            Text(errorText),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
