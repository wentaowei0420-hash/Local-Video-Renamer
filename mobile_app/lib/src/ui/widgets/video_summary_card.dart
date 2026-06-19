import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../../database/video_list_item.dart';
import '../theme/app_design.dart';
import '../theme/app_icons.dart';
import 'video_cover_thumbnail.dart';

class VideoSummaryCard extends StatelessWidget {
  const VideoSummaryCard({
    super.key,
    required this.item,
    this.onTap,
  });

  final VideoListItem item;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final semanticsLabel = [
      if (item.code.isNotEmpty) item.code,
      if (item.title.isNotEmpty) item.title,
      if (item.author.isNotEmpty) item.author,
    ].join(', ');

    return Semantics(
      button: onTap != null,
      label: onTap == null ? semanticsLabel : 'Open video detail: $semanticsLabel',
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isCompact = constraints.maxWidth < 360;
          final cover = VideoCoverThumbnail(
            code: item.code,
            title: item.title,
            category: item.videoCategory,
            maker: item.maker,
            height: isCompact ? 196 : 152,
            width: isCompact ? constraints.maxWidth - 36 : 108,
            heroTag: 'video-cover-${item.code}',
            borderRadius: isCompact ? 24 : 20,
          );

          return Card(
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: onTap,
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: isCompact
                    ? Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          cover,
                          const SizedBox(height: 16),
                          _VideoDetails(item: item, onTap: onTap),
                        ],
                      )
                    : Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          cover,
                          const SizedBox(width: 16),
                          Expanded(
                            child: _VideoDetails(item: item, onTap: onTap),
                          ),
                        ],
                      ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _VideoDetails extends StatelessWidget {
  const _VideoDetails({
    required this.item,
    required this.onTap,
  });

  final VideoListItem item;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final metaValues = <String>[
      if (item.releaseDate.isNotEmpty) '日期 ${item.releaseDate}',
      if (item.duration.isNotEmpty) '时长 ${item.duration}',
      if (item.size.isNotEmpty) '大小 ${item.size}',
    ];

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Wrap(
                spacing: 10,
                runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    item.code.isEmpty ? '未命名编号' : item.code,
                    style: GoogleFonts.jetBrainsMono(
                      textStyle: theme.textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.6,
                        color: AppDesign.ink,
                      ),
                    ),
                  ),
                  if (item.enrichmentStatus.isNotEmpty)
                    _Badge(
                      text: item.enrichmentStatus,
                      foreground: AppDesign.amber,
                      background: AppDesign.amberSoft,
                    ),
                  if (item.videoCategory.isNotEmpty)
                    _Badge(
                      text: item.videoCategory,
                      foreground: AppDesign.teal,
                      background: AppDesign.tealSoft,
                    ),
                ],
              ),
            ),
            if (onTap != null)
              const Padding(
                padding: EdgeInsets.only(left: 12, top: 2),
                child: Icon(
                  LucideIcons.chevronRight,
                  color: AppDesign.inkMuted,
                  size: 18,
                ),
              ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          item.title.isEmpty ? item.code : item.title,
          maxLines: 3,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            height: 1.35,
            color: AppDesign.ink,
          ),
        ),
        if (item.author.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            item.author,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: AppDesign.inkMuted,
            ),
          ),
        ],
        if (metaValues.isNotEmpty) ...[
          const SizedBox(height: 14),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final value in metaValues) _MetaPill(text: value),
            ],
          ),
        ],
        if (item.storageLocation.isNotEmpty) ...[
          const SizedBox(height: 14),
          _HighlightedDetail(
            icon: LucideIcons.folderOpen,
            label: '存储位置',
            value: item.storageLocation,
          ),
        ],
        if (item.maker.isNotEmpty || item.publisher.isNotEmpty) ...[
          const SizedBox(height: 12),
          if (item.maker.isNotEmpty) _DetailLine(label: '制作商', value: item.maker),
          if (item.publisher.isNotEmpty) ...[
            const SizedBox(height: 8),
            _DetailLine(label: '发行商', value: item.publisher),
          ],
        ],
      ],
    );
  }
}

class _MetaPill extends StatelessWidget {
  const _MetaPill({
    required this.text,
  });

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: AppDesign.surfaceMuted,
        borderRadius: BorderRadius.circular(AppDesign.chipRadius),
        border: Border.all(color: AppDesign.border),
      ),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: AppDesign.inkMuted,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }
}

class _HighlightedDetail extends StatelessWidget {
  const _HighlightedDetail({
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
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppDesign.indigoSoft,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: EdgeInsets.only(top: 2),
            child: Icon(
              icon,
              size: 16,
              color: AppDesign.indigo,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: AppDesign.indigo,
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 3),
                Text(
                  value,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppDesign.ink,
                        fontWeight: FontWeight.w600,
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

class _DetailLine extends StatelessWidget {
  const _DetailLine({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 66,
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: AppDesign.inkMuted,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppDesign.ink,
                  fontWeight: FontWeight.w500,
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
        borderRadius: BorderRadius.circular(AppDesign.chipRadius),
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
