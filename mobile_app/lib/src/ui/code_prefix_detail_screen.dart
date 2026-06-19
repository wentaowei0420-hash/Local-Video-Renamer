import 'dart:async';

import 'package:flutter/material.dart';

import '../database/code_prefix_detail.dart';
import '../database/library_detail_repository.dart';
import 'detail_routes.dart';
import 'theme/app_icons.dart';
import 'video_detail_screen.dart' show DetailEmptyState, DetailErrorState;
import 'widgets/animated_reveal.dart';
import 'widgets/video_summary_card.dart';

class CodePrefixDetailScreen extends StatefulWidget {
  const CodePrefixDetailScreen({
    super.key,
    required this.databasePath,
    required this.prefix,
  });

  final String databasePath;
  final String prefix;

  @override
  State<CodePrefixDetailScreen> createState() => _CodePrefixDetailScreenState();
}

class _CodePrefixDetailScreenState extends State<CodePrefixDetailScreen> {
  late final LibraryDetailRepository _repository;
  late Future<CodePrefixDetail?> _detailFuture;

  @override
  void initState() {
    super.initState();
    _repository = LibraryDetailRepository(databasePath: widget.databasePath);
    _detailFuture = _repository.fetchCodePrefixDetail(widget.prefix);
  }

  @override
  void dispose() {
    unawaited(_repository.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('番号详情'),
      ),
      body: FutureBuilder<CodePrefixDetail?>(
        future: _detailFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return DetailErrorState(
              title: '番号详情读取失败',
              errorText: snapshot.error.toString(),
              onRetry: () {
                setState(() {
                  _detailFuture = _repository.fetchCodePrefixDetail(widget.prefix);
                });
              },
            );
          }

          final detail = snapshot.data;
          if (detail == null) {
            return const DetailEmptyState(
              title: '没有找到这个番号前缀',
              description: '当前数据库中没有对应番号分组。',
            );
          }

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            children: [
              AnimatedReveal(
                child: Container(
                  padding: const EdgeInsets.all(22),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(28),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [Color(0xFF2B233A), Color(0xFF705C8D)],
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        detail.prefix,
                        style: theme.textTheme.headlineMedium?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.8,
                        ),
                      ),
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          _PrefixFactChip(label: '作品数', value: '${detail.movieCount}'),
                          if (detail.indexedVideoCount > 0)
                            _PrefixFactChip(label: '索引数', value: '${detail.indexedVideoCount}'),
                          if (detail.sampleCategory.isNotEmpty)
                            _PrefixFactChip(label: '分类', value: detail.sampleCategory),
                          if (detail.enrichmentStatus.isNotEmpty)
                            _PrefixFactChip(label: '补全', value: detail.enrichmentStatus),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              if (detail.latestReleaseDate.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 70),
                  child: Card(
                    child: ListTile(
                      leading: const Icon(LucideIcons.calendarDays, size: 18),
                      title: const Text('最近收录日期'),
                      subtitle: Text(detail.latestReleaseDate),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              AnimatedReveal(
                delay: const Duration(milliseconds: 110),
                child: Text(
                  '相关视频',
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (detail.videos.isEmpty)
                const AnimatedReveal(
                  delay: Duration(milliseconds: 150),
                  child: DetailEmptyState(
                    title: '这个番号前缀暂时没有关联视频',
                    description: '可以稍后重新导入数据库再看看。',
                  ),
                )
              else
                for (var index = 0; index < detail.videos.length; index++) ...[
                  AnimatedReveal(
                    delay: Duration(milliseconds: 150 + 30 * (index.clamp(0, 8))),
                    child: VideoSummaryCard(
                      item: detail.videos[index],
                      onTap: () {
                        openVideoDetail(
                          context,
                          databasePath: widget.databasePath,
                          code: detail.videos[index].code,
                          replaceCurrent: true,
                        );
                      },
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
            ],
          );
        },
      ),
    );
  }
}

class _PrefixFactChip extends StatelessWidget {
  const _PrefixFactChip({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: Colors.white70,
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 2),
          Text(
            value,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}
