import 'actor_list_item.dart';

class ActorSearchResult {
  const ActorSearchResult({
    required this.items,
    required this.totalCount,
    required this.limit,
    required this.offset,
  });

  final List<ActorListItem> items;
  final int totalCount;
  final int limit;
  final int offset;

  bool get hasMore => offset + items.length < totalCount;
  bool get hasPrevious => offset > 0;
  int get currentPage => limit <= 0 ? 1 : (offset ~/ limit) + 1;
  int get totalPages => totalCount == 0 || limit <= 0 ? 1 : ((totalCount - 1) ~/ limit) + 1;
}
