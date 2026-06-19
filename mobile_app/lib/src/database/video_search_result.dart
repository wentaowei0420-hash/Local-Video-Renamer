import 'video_list_item.dart';

class VideoSearchResult {
  const VideoSearchResult({
    required this.items,
    required this.totalCount,
    required this.limit,
  });

  final List<VideoListItem> items;
  final int totalCount;
  final int limit;

  bool get hasMore => totalCount > items.length;
}
