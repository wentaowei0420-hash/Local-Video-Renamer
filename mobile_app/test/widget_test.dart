import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_app/src/database/video_list_item.dart';
import 'package:mobile_app/src/ui/widgets/result_pagination_bar.dart';
import 'package:mobile_app/src/ui/widgets/video_cover_thumbnail.dart';
import 'package:mobile_app/src/ui/widgets/video_summary_card.dart';

void main() {
  const sampleItem = VideoListItem(
    code: 'ABP-123',
    title: 'A Very Long Offline Library Entry Title',
    author: 'Sample Actor',
    duration: '120 min',
    size: '4.7 GB',
    storageLocation: '/storage/emulated/0/Movies/ABP-123.mp4',
    releaseDate: '2024-05-20',
    maker: 'Studio Alpha',
    publisher: 'Publisher Beta',
    videoCategory: 'Drama',
    enrichmentStatus: 'Complete',
  );

  Future<void> pumpCard(
    WidgetTester tester, {
    required double width,
    VoidCallback? onTap,
  }) {
    return tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: Align(
              alignment: Alignment.topCenter,
              child: SizedBox(
                width: width,
                child: VideoSummaryCard(
                  item: sampleItem,
                  onTap: onTap,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  testWidgets('video summary card stacks cover above text on narrow widths', (tester) async {
    await pumpCard(tester, width: 320);

    final coverTopLeft = tester.getTopLeft(find.byType(VideoCoverThumbnail));
    final titleTopLeft = tester.getTopLeft(find.text(sampleItem.title));

    expect((titleTopLeft.dx - coverTopLeft.dx).abs(), lessThan(24));
    expect(titleTopLeft.dy, greaterThan(coverTopLeft.dy + 120));
  });

  testWidgets('video summary card exposes a clear semantics label when tappable', (tester) async {
    final semanticsHandle = tester.ensureSemantics();

    await pumpCard(
      tester,
      width: 420,
      onTap: () {},
    );

    expect(find.bySemanticsLabel('Open video detail: ABP-123, A Very Long Offline Library Entry Title, Sample Actor'), findsOneWidget);

    semanticsHandle.dispose();
  });

  testWidgets('pagination bar shows numbered buttons with ellipsis for long result sets', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ResultPaginationBar(
            totalCount: 1318,
            currentPage: 6,
            totalPages: 14,
            currentItemCount: 100,
            itemLabel: 'items',
            onPageSelected: (_) {},
          ),
        ),
      ),
    );

    expect(find.widgetWithText(OutlinedButton, '1'), findsOneWidget);
    expect(find.text('...'), findsNWidgets(2));
    expect(find.widgetWithText(OutlinedButton, '5'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, '6'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '7'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, '14'), findsOneWidget);
  });

  testWidgets('pagination bar notifies selected page when a page button is tapped', (tester) async {
    var selectedPage = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ResultPaginationBar(
            totalCount: 1318,
            currentPage: 6,
            totalPages: 14,
            currentItemCount: 100,
            itemLabel: 'items',
            onPageSelected: (page) => selectedPage = page,
          ),
        ),
      ),
    );

    await tester.tap(find.widgetWithText(OutlinedButton, '7'));
    await tester.pump();

    expect(selectedPage, 7);
  });
}
