import 'package:sqflite/sqflite.dart';

import 'code_prefix_list_item.dart';
import 'code_prefix_search_result.dart';

class CodePrefixLibraryRepository {
  CodePrefixLibraryRepository({
    required this.databasePath,
  });

  final String databasePath;
  Future<Database>? _databaseFuture;

  static const int defaultLimit = 100;

  Future<CodePrefixSearchResult> searchPrefixes({
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
          c.prefix LIKE ? COLLATE NOCASE
          OR COALESCE(NULLIF(c.code, ''), '') LIKE ? COLLATE NOCASE
          OR COALESCE(NULLIF(c.title, ''), '') LIKE ?
          OR COALESCE(NULLIF(c.author, ''), '') LIKE ?
          OR COALESCE(NULLIF(c.video_category, ''), '') LIKE ?
        '''
        : '1 = 1';

    final whereArgs = hasQuery
        ? <Object?>[pattern, pattern, pattern, pattern, pattern]
        : <Object?>[];

    final countRows = await database.rawQuery(
      '''
      SELECT COUNT(*) AS total_count
      FROM (
        SELECT c.prefix
        FROM code_prefix_movies c
        WHERE $whereClause
        GROUP BY c.prefix
      ) matched_prefixes
      ''',
      whereArgs,
    );
    final totalCount = (countRows.first['total_count'] as int?) ?? 0;

    final itemRows = await database.rawQuery(
      '''
      SELECT
        c.prefix,
        COUNT(c.code) AS movie_count,
        MAX(COALESCE(NULLIF(c.javtxt_release_date, ''), NULLIF(c.release_date, ''), '')) AS latest_release_date,
        MAX(COALESCE(NULLIF(c.video_category, ''), '')) AS sample_category,
        MAX(COALESCE(NULLIF(c.code, ''), '')) AS sample_code,
        MAX(COALESCE(NULLIF(c.title, ''), '')) AS sample_title,
        MAX(COALESCE(NULLIF(c.author, ''), '')) AS sample_author,
        MAX(
          COALESCE(
            NULLIF(e.javtxt_enrichment_status, ''),
            NULLIF(e.avfan_enrichment_status, ''),
            NULLIF(e.enrichment_status, ''),
            ''
          )
        ) AS enrichment_status,
        MAX(COALESCE(e.javtxt_total_videos, e.avfan_total_videos, 0)) AS indexed_video_count
      FROM code_prefix_movies c
      LEFT JOIN code_prefix_enrichments e ON e.prefix = c.prefix
      WHERE $whereClause
      GROUP BY c.prefix
      ORDER BY movie_count DESC, c.prefix COLLATE NOCASE ASC
      LIMIT ?
      OFFSET ?
      ''',
      <Object?>[
        ...whereArgs,
        limit,
        offset,
      ],
    );

    return CodePrefixSearchResult(
      items: itemRows.map(CodePrefixListItem.fromMap).toList(growable: false),
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
