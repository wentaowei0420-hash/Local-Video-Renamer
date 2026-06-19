import 'package:flutter/material.dart';

import '../theme/app_design.dart';

class ResultPaginationBar extends StatelessWidget {
  const ResultPaginationBar({
    super.key,
    required this.totalCount,
    required this.currentPage,
    required this.totalPages,
    required this.currentItemCount,
    required this.onPageSelected,
    required this.itemLabel,
  });

  final int totalCount;
  final int currentPage;
  final int totalPages;
  final int currentItemCount;
  final ValueChanged<int> onPageSelected;
  final String itemLabel;

  List<int?> _visiblePages() {
    if (totalPages <= 7) {
      return List<int?>.generate(totalPages, (index) => index + 1);
    }

    final pages = <int?>[1];
    final start = currentPage <= 4
        ? 2
        : currentPage >= totalPages - 3
            ? totalPages - 4
            : currentPage - 1;
    final end = currentPage <= 4
        ? 5
        : currentPage >= totalPages - 3
            ? totalPages - 1
            : currentPage + 1;

    if (start > 2) {
      pages.add(null);
    }

    for (var page = start; page <= end; page++) {
      if (page > 1 && page < totalPages) {
        pages.add(page);
      }
    }

    if (end < totalPages - 1) {
      pages.add(null);
    }

    pages.add(totalPages);
    return pages;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final previousEnabled = currentPage > 1;
    final nextEnabled = currentPage < totalPages;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppDesign.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppDesign.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '共 $totalCount $itemLabel，第 $currentPage / $totalPages 页，本页 $currentItemCount 条',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppDesign.ink,
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              OutlinedButton(
                onPressed: previousEnabled ? () => onPageSelected(currentPage - 1) : null,
                child: const Text('上一页'),
              ),
              for (final page in _visiblePages())
                page == null
                    ? Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 2),
                        child: Text(
                          '...',
                          style: theme.textTheme.titleSmall?.copyWith(
                            color: AppDesign.inkMuted,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      )
                    : _PageButton(
                        page: page,
                        selected: page == currentPage,
                        onTap: () => onPageSelected(page),
                      ),
              FilledButton(
                onPressed: nextEnabled ? () => onPageSelected(currentPage + 1) : null,
                child: const Text('下一页'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PageButton extends StatelessWidget {
  const _PageButton({
    required this.page,
    required this.selected,
    required this.onTap,
  });

  final int page;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 42,
      height: 42,
      child: selected
          ? FilledButton(
              onPressed: onTap,
              style: FilledButton.styleFrom(
                padding: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              child: Text('$page'),
            )
          : OutlinedButton(
              onPressed: onTap,
              style: OutlinedButton.styleFrom(
                padding: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              child: Text('$page'),
            ),
    );
  }
}
