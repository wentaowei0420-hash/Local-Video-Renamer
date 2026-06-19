import 'package:sqflite/sqflite.dart';

import 'video_list_item.dart';
import 'video_search_result.dart';

class VideoLibraryRepository {
  VideoLibraryRepository({
    required this.databasePath,
  });

  final String databasePath;
  Future<Database>? _databaseFuture;

  static const int defaultLimit = 100;

  Future<VideoSearchResult> searchVideos({
    String query = '',
    int limit = defaultLimit,
    int offset = 0,
  }) async {
    final database = await _openDatabase();
    final normalizedQuery = query.trim();
    final hasQuery = normalizedQuery.isNotEmpty;
    final pattern = '%$normalizedQuery%';

    final whereClause = hasQuery
        ? '''
          code LIKE ? COLLATE NOCASE
          OR COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), '') LIKE ?
          OR COALESCE(NULLIF(title, ''), '') LIKE ?
          OR COALESCE(NULLIF(author, ''), '') LIKE ?
          OR COALESCE(NULLIF(storage_location, ''), '') LIKE ?
        '''
        : '1 = 1';

    final whereArgs = hasQuery
        ? <Object?>[pattern, pattern, pattern, pattern, pattern]
        : <Object?>[];

    final countRows = await database.rawQuery(
      'SELECT COUNT(*) AS total_count FROM processed_videos WHERE $whereClause',
      whereArgs,
    );
    final totalCount = (countRows.first['total_count'] as int?) ?? 0;

    final itemRows = await database.rawQuery(
      '''
      SELECT
        code,
        COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code) AS display_title,
        COALESCE(NULLIF(author, ''), '') AS author,
        COALESCE(NULLIF(duration, ''), '') AS duration,
        COALESCE(NULLIF(size, ''), '') AS size,
        COALESCE(NULLIF(storage_location, ''), '') AS storage_location,
        COALESCE(NULLIF(javtxt_release_date, ''), NULLIF(release_date, ''), '') AS display_release_date,
        COALESCE(NULLIF(maker, ''), '') AS maker,
        COALESCE(NULLIF(publisher, ''), '') AS publisher,
        COALESCE(NULLIF(video_category, ''), '') AS video_category,
        COALESCE(NULLIF(enrichment_status, ''), '') AS enrichment_status
      FROM processed_videos
      WHERE $whereClause
      ORDER BY
        CASE
          WHEN COALESCE(NULLIF(javtxt_release_date, ''), NULLIF(release_date, ''), '') = '' THEN 1
          ELSE 0
        END,
        COALESCE(NULLIF(javtxt_release_date, ''), NULLIF(release_date, ''), '') DESC,
        code DESC
      LIMIT ?
      OFFSET ?
      ''',
      <Object?>[
        ...whereArgs,
        limit,
        offset,
      ],
    );

    return VideoSearchResult(
      items: itemRows.map(VideoListItem.fromMap).toList(growable: false),
      totalCount: totalCount,
      limit: limit,
      offset: offset,
    );
  }

  Future<void> dispose() async {
    final future = _databaseFuture;
    _databaseFuture = null;
    if (future == null) {
      return;
    }
    final database = await future;
    await database.close();
  }

  Future<Database> _openDatabase() {
    return _databaseFuture ??= openDatabase(
      databasePath,
      readOnly: true,
      singleInstance: false,
    );
  }
}
