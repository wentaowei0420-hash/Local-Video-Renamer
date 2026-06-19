import 'dart:async';

import 'package:flutter/material.dart';

import '../database/database_status.dart';
import '../database/video_library_repository.dart';
import '../database/video_search_result.dart';
import 'detail_routes.dart';
import 'theme/app_icons.dart';
import 'widgets/animated_reveal.dart';
import 'widgets/result_pagination_bar.dart';
import 'widgets/video_summary_card.dart';

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
  static const int _pageSize = 100;

  late final VideoLibraryRepository _repository;
  final TextEditingController _searchController = TextEditingController();
  Timer? _searchDebounce;
  late Future<VideoSearchResult> _resultFuture;
  String _query = '';
  int _currentPage = 1;

  @override
  void initState() {
    super.initState();
    _repository = VideoLibraryRepository(
      databasePath: widget.databaseStatus.databasePath,
    );
    _resultFuture = _loadPage();
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    unawaited(_repository.dispose());
    super.dispose();
  }

  Future<VideoSearchResult> _loadPage({
    String? query,
    int? page,
  }) {
    final nextQuery = query ?? _query;
    final nextPage = page ?? _currentPage;
    return _repository.searchVideos(
      query: nextQuery,
      limit: _pageSize,
      offset: (nextPage - 1) * _pageSize,
    );
  }

  Future<void> _reload() async {
    widget.onRefreshDatabaseStatus();
    setState(() {
      _resultFuture = _loadPage();
    });
    await _resultFuture;
  }

  void _goToPage(int page) {
    setState(() {
      _currentPage = page;
      _resultFuture = _loadPage(page: page);
    });
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
        _currentPage = 1;
        _resultFuture = _loadPage(query: _query, page: 1);
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
      _currentPage = 1;
      _resultFuture = _loadPage(query: '', page: 1);
    });
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _reload,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
        children: [
          AnimatedReveal(
            child: TextField(
              controller: _searchController,
              onChanged: _handleSearchChanged,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: '搜索番号、标题、演员、存储位置',
                prefixIcon: const Icon(LucideIcons.search, size: 18),
                suffixIcon: _query.isEmpty
                    ? null
                    : IconButton(
                        onPressed: _clearSearch,
                        icon: const Icon(LucideIcons.x, size: 18),
                      ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 280),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, animation) {
              return FadeTransition(
                opacity: animation,
                child: SlideTransition(
                  position: Tween<Offset>(
                    begin: const Offset(0, 0.04),
                    end: Offset.zero,
                  ).animate(animation),
                  child: child,
                ),
              );
            },
            child: FutureBuilder<VideoSearchResult>(
              key: ValueKey<String>('video-$_query-$_currentPage'),
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
                        _resultFuture = _loadPage();
                      });
                    },
                  );
                }

                final result = snapshot.data!;
                return Column(
                  key: ValueKey<String>('video-result-$_query-${result.currentPage}-${result.totalCount}'),
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ResultPaginationBar(
                      totalCount: result.totalCount,
                      currentPage: result.currentPage,
                      totalPages: result.totalPages,
                      currentItemCount: result.items.length,
                      itemLabel: '条',
                      onPageSelected: _goToPage,
                    ),
                    const SizedBox(height: 12),
                    if (result.items.isEmpty)
                      const _EmptyVideoState()
                    else
                      for (var index = 0; index < result.items.length; index++) ...[
                        AnimatedReveal(
                          delay: Duration(milliseconds: 30 * (index.clamp(0, 8))),
                          child: VideoSummaryCard(
                            item: result.items[index],
                            onTap: () {
                              openVideoDetail(
                                context,
                                databasePath: widget.databaseStatus.databasePath,
                                code: result.items[index].code,
                              );
                            },
                          ),
                        ),
                        const SizedBox(height: 12),
                      ],
                    if (result.items.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      ResultPaginationBar(
                        totalCount: result.totalCount,
                        currentPage: result.currentPage,
                        totalPages: result.totalPages,
                        currentItemCount: result.items.length,
                        itemLabel: '条',
                        onPageSelected: _goToPage,
                      ),
                    ],
                  ],
                );
              },
            ),
          ),
        ],
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
            const Icon(LucideIcons.searchX, size: 30),
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
              icon: const Icon(LucideIcons.refreshCw, size: 18),
              label: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}
