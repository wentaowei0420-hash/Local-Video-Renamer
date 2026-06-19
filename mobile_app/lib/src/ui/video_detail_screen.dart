import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../database/library_detail_repository.dart';
import '../database/video_detail.dart';
import 'detail_routes.dart';
import 'theme/app_icons.dart';
import 'widgets/animated_reveal.dart';
import 'widgets/video_cover_thumbnail.dart';

class VideoDetailScreen extends StatefulWidget {
  const VideoDetailScreen({
    super.key,
    required this.databasePath,
    required this.videoCode,
  });

  final String databasePath;
  final String videoCode;

  @override
  State<VideoDetailScreen> createState() => _VideoDetailScreenState();
}

class _VideoDetailScreenState extends State<VideoDetailScreen> {
  late final LibraryDetailRepository _repository;
  late Future<VideoDetail?> _detailFuture;

  @override
  void initState() {
    super.initState();
    _repository = LibraryDetailRepository(databasePath: widget.databasePath);
    _detailFuture = _repository.fetchVideoDetail(widget.videoCode);
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
        title: const Text('视频详情'),
      ),
      body: FutureBuilder<VideoDetail?>(
        future: _detailFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snapshot.hasError) {
            return DetailErrorState(
              title: '视频详情读取失败',
              errorText: snapshot.error.toString(),
              onRetry: () {
                setState(() {
                  _detailFuture = _repository.fetchVideoDetail(widget.videoCode);
                });
              },
            );
          }

          final detail = snapshot.data;
          if (detail == null) {
            return const DetailEmptyState(
              title: '没有找到这条视频',
              description: '这条记录可能已被删除，或者当前数据库中没有对应编号。',
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
                      colors: [Color(0xFF2A211F), Color(0xFF734738)],
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          VideoCoverThumbnail(
                            code: detail.code,
                            title: detail.title,
                            category: detail.videoCategory,
                            maker: detail.maker,
                            height: 188,
                            width: 134,
                            heroTag: 'video-cover-${detail.code}',
                            borderRadius: 24,
                          ),
                          const SizedBox(width: 18),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  detail.code,
                                  style: GoogleFonts.jetBrainsMono(
                                    textStyle: theme.textTheme.headlineMedium?.copyWith(
                                      color: Colors.white,
                                      fontWeight: FontWeight.w800,
                                      letterSpacing: 0.8,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 10),
                                Text(
                                  detail.title.isEmpty ? detail.code : detail.title,
                                  style: theme.textTheme.titleLarge?.copyWith(
                                    color: Colors.white,
                                    height: 1.4,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                if (detail.author.isNotEmpty) ...[
                                  const SizedBox(height: 12),
                                  Text(
                                    detail.author,
                                    style: theme.textTheme.bodyLarge?.copyWith(
                                      color: Colors.white.withValues(alpha: 0.88),
                                    ),
                                  ),
                                ],
                                if (detail.enrichmentStatus.isNotEmpty) ...[
                                  const SizedBox(height: 12),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                    decoration: BoxDecoration(
                                      color: Colors.white.withValues(alpha: 0.14),
                                      borderRadius: BorderRadius.circular(999),
                                    ),
                                    child: Text(
                                      detail.enrichmentStatus,
                                      style: theme.textTheme.labelLarge?.copyWith(
                                        color: Colors.white,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              if (detail.storageLocation.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 70),
                  child: _HighlightCard(
                    icon: LucideIcons.folderOpen,
                    title: '物理文件存放位置',
                    value: detail.storageLocation,
                  ),
                ),
              ],
              const SizedBox(height: 16),
              AnimatedReveal(
                delay: const Duration(milliseconds: 110),
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(18),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '详细信息',
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 14),
                        _MetaLine(label: '发行日期', value: detail.releaseDate),
                        _MetaLine(label: '制作商', value: detail.maker),
                        _MetaLine(label: '发行商', value: detail.publisher),
                        _MetaLine(label: '文件大小', value: detail.size),
                        _MetaLine(label: '视频时长', value: detail.duration),
                        _MetaLine(label: '分类', value: detail.videoCategory),
                        _MetaLine(label: '补全状态', value: detail.enrichmentStatus),
                      ],
                    ),
                  ),
                ),
              ),
              if (detail.prefix.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 150),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '所属番号库',
                            style: theme.textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 14),
                          ActionChip(
                            avatar: const Icon(LucideIcons.layoutGrid, size: 18),
                            label: Text(detail.prefix),
                            onPressed: () {
                              openCodePrefixDetail(
                                context,
                                databasePath: widget.databasePath,
                                prefix: detail.prefix,
                                replaceCurrent: true,
                              );
                            },
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
              if (detail.actors.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 190),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '出演演员',
                            style: theme.textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 14),
                          Wrap(
                            spacing: 10,
                            runSpacing: 10,
                            children: [
                              for (final actorName in detail.actors)
                                ActionChip(
                                  avatar: const Icon(LucideIcons.user2, size: 18),
                                  label: Text(actorName),
                                  onPressed: () {
                                    openActorDetail(
                                      context,
                                      databasePath: widget.databasePath,
                                      actorName: actorName,
                                      replaceCurrent: true,
                                    );
                                  },
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
              if (detail.tagList.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 230),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '标签',
                            style: theme.textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 14),
                          Wrap(
                            spacing: 10,
                            runSpacing: 10,
                            children: [
                              for (final tag in detail.tagList)
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFFF4ECE5),
                                    borderRadius: BorderRadius.circular(999),
                                  ),
                                  child: Text(tag),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
              if (detail.description.isNotEmpty) ...[
                const SizedBox(height: 16),
                AnimatedReveal(
                  delay: const Duration(milliseconds: 270),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '简介',
                            style: theme.textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            detail.description,
                            style: theme.textTheme.bodyLarge?.copyWith(height: 1.5),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ],
          );
        },
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
    if (value.isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 76,
            child: Text(
              label,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: const Color(0xFF8A7E75),
                    fontWeight: FontWeight.w700,
                  ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

class _HighlightCard extends StatelessWidget {
  const _HighlightCard({
    required this.icon,
    required this.title,
    required this.value,
  });

  final IconData icon;
  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF54403A), Color(0xFF8E3B2E)],
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(icon, color: Colors.white),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: Colors.white70,
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class DetailErrorState extends StatelessWidget {
  const DetailErrorState({
    super.key,
    required this.title,
    required this.errorText,
    required this.onRetry,
  });

  final String title;
  final String errorText;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
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
        ),
      ),
    );
  }
}

class DetailEmptyState extends StatelessWidget {
  const DetailEmptyState({
    super.key,
    required this.title,
    required this.description,
  });

  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(LucideIcons.inbox, size: 30),
                const SizedBox(height: 12),
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 8),
                Text(
                  description,
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
