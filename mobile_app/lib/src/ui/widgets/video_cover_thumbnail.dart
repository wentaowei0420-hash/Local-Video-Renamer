import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../theme/app_icons.dart';
import '../theme/app_design.dart';

class VideoCoverThumbnail extends StatelessWidget {
  const VideoCoverThumbnail({
    super.key,
    required this.code,
    required this.title,
    required this.category,
    required this.maker,
    this.height = 144,
    this.width = 104,
    this.heroTag,
    this.borderRadius = 22,
  });

  final String code;
  final String title;
  final String category;
  final String maker;
  final double height;
  final double width;
  final String? heroTag;
  final double borderRadius;

  @override
  Widget build(BuildContext context) {
    final poster = Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(borderRadius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: _gradientForCode(code),
        ),
        border: Border.all(
          color: Colors.white.withValues(alpha: 0.28),
        ),
        boxShadow: AppDesign.softShadow,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(borderRadius),
        child: Stack(
          children: [
            Positioned(
              right: -18,
              top: -12,
              child: Icon(
                LucideIcons.playCircle,
                size: width * 0.72,
                color: Colors.white.withValues(alpha: 0.14),
              ),
            ),
            Positioned.fill(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      Colors.white.withValues(alpha: 0.04),
                      Colors.black.withValues(alpha: 0.14),
                      Colors.black.withValues(alpha: 0.34),
                    ],
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (category.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(999),
                        border: Border.all(color: Colors.white24),
                      ),
                      child: Text(
                        category,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                              color: Colors.white,
                              fontWeight: FontWeight.w800,
                            ),
                      ),
                    ),
                  const Spacer(),
                  Text(
                    code.isEmpty ? 'NO CODE' : code,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: GoogleFonts.jetBrainsMono(
                      textStyle: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 0.8,
                          ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _posterSubtitle(),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Colors.white.withValues(alpha: 0.88),
                          height: 1.3,
                        ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );

    if (heroTag == null) {
      return poster;
    }

    return Hero(
      tag: heroTag!,
      child: poster,
    );
  }

  String _posterSubtitle() {
    if (maker.isNotEmpty) {
      return maker;
    }
    if (title.isNotEmpty) {
      return title;
    }
    return '离线封面预览';
  }

  static List<Color> _gradientForCode(String input) {
    const palettes = <List<Color>>[
      [Color(0xFF5C372C), Color(0xFFAF7656)],
      [Color(0xFF243A52), Color(0xFF628BBE)],
      [Color(0xFF1F433A), Color(0xFF4E8E76)],
      [Color(0xFF3A3158), Color(0xFF7571B8)],
      [Color(0xFF4A3421), Color(0xFFA37C3C)],
      [Color(0xFF26384A), Color(0xFF63809D)],
    ];

    final normalized = input.trim();
    if (normalized.isEmpty) {
      return palettes.first;
    }

    final hash = normalized.codeUnits.fold<int>(0, (sum, value) => sum + value);
    return palettes[hash % palettes.length];
  }
}
