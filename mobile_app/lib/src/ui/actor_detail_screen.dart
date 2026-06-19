import 'dart:async';

import 'package:flutter/material.dart';

import '../database/actor_detail.dart';
import '../database/library_detail_repository.dart';
import 'detail_routes.dart';
import 'theme/app_icons.dart';
import 'video_detail_screen.dart' show DetailEmptyState, DetailErrorState;
import 'widgets/animated_reveal.dart';
import 'widgets/video_summary_card.dart';

class ActorDetailScreen extends StatefulWidget {
  const ActorDetailScreen({
    super.key,
    required this.databasePath,
    required this.actorName,
  });

  final String databasePath;
  final String actorName;

  @override
  State<ActorDetailScreen> createState() => _ActorDetailScreenState();
}

class _ActorDetailScreenState extends State<ActorDetailScreen> {
  late final LibraryDetailRepository _repository;
  late Future<ActorDetail?> _detailFuture;

  @override
  void initState() {
    super.initState();
    _repository = LibraryDetailRepository(databasePath: widget.databasePath);
    _detailFuture = _repository.fetchActorDetail(widget.actorName);
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
        title: const Text('演员档案'),
      ),
      body: FutureBuilder<ActorDetail?>(
        future: _detailFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return DetailErrorState(
              title: '演员详情读取失败',
              errorText: snapshot.error.toString(),
              onRetry: () {
                setState(() {
                  _detailFuture = _repository.fetchActorDetail(widget.actorName);
                });
              },
            );
          }

          final detail = snapshot.data;
          if (detail == null) {
            return const DetailEmptyState(
              title: '没有找到这位演员',
              description: '当前数据库中没有对应演员档案。',
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
                      colors: [Color(0xFF243238), Color(0xFF4E7567)],
                    ),
                  ),
                  child: Column(
                    children: [
                      Container(
                        width: 72,
                        height: 72,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.16),
                          shape: BoxShape.circle,
                        ),
                        child: Text(
                          detail.name.isEmpty ? '?' : detail.name.characters.first,
                          style: theme.textTheme.headlineMedium?.copyWith(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        detail.name,
                        textAlign: TextAlign.center,
                        style: theme.textTheme.headlineSmall?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Wrap(
                        alignment: WrapAlignment.center,
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          _ActorFactChip(label: '作品数', value: '${detail.movieCount}'),
                          if (detail.age.isNotEmpty) _ActorFactChip(label: '年龄', value: detail.age),
                          if (detail.birthday.isNotEmpty) _ActorFactChip(label: '生日', value: detail.birthday),
                          _ActorFactChip(label: '匹配状态', value: detail.isMatched ? '已匹配' : '未匹配'),
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
                    title: '这位演员暂时没有关联视频',
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

class _ActorFactChip extends StatelessWidget {
  const _ActorFactChip({
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
