import 'package:sqflite/sqflite.dart';

import 'actor_list_item.dart';
import 'actor_search_result.dart';

class ActorLibraryRepository {
  ActorLibraryRepository({
    required this.databasePath,
  });

  final String databasePath;
  Future<Database>? _databaseFuture;

  static const int defaultLimit = 100;

  Future<ActorSearchResult> searchActors({
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
          a.name LIKE ? COLLATE NOCASE
          OR COALESCE(NULLIF(a.birthday, ''), '') LIKE ?
          OR COALESCE(NULLIF(a.age, ''), '') LIKE ?
          OR COALESCE(NULLIF(am.code, ''), '') LIKE ? COLLATE NOCASE
          OR COALESCE(NULLIF(am.title, ''), '') LIKE ?
        '''
        : '1 = 1';

    final whereArgs = hasQuery
        ? <Object?>[pattern, pattern, pattern, pattern, pattern]
        : <Object?>[];

    final countRows = await database.rawQuery(
      '''
      SELECT COUNT(*) AS total_count
      FROM (
        SELECT a.name
        FROM actors a
        LEFT JOIN actor_movies am ON am.actor_name = a.name
        WHERE $whereClause
        GROUP BY a.name
      ) matched_actors
      ''',
      whereArgs,
    );
    final totalCount = (countRows.first['total_count'] as int?) ?? 0;

    final itemRows = await database.rawQuery(
      '''
      SELECT
        a.name,
        COALESCE(NULLIF(a.birthday, ''), '') AS birthday,
        COALESCE(NULLIF(a.age, ''), '') AS age,
        COALESCE(a.matched, 0) AS matched,
        COUNT(am.code) AS movie_count,
        MAX(COALESCE(NULLIF(am.javtxt_release_date, ''), NULLIF(am.release_date, ''), '')) AS latest_release_date,
        MAX(COALESCE(NULLIF(am.video_category, ''), '')) AS sample_category,
        MAX(COALESCE(NULLIF(am.code, ''), '')) AS sample_code,
        MAX(COALESCE(NULLIF(am.title, ''), '')) AS sample_title
      FROM actors a
      LEFT JOIN actor_movies am ON am.actor_name = a.name
      WHERE $whereClause
      GROUP BY a.name, a.birthday, a.age, a.matched
      ORDER BY movie_count DESC, a.name COLLATE NOCASE ASC
      LIMIT ?
      OFFSET ?
      ''',
      <Object?>[
        ...whereArgs,
        limit,
        offset,
      ],
    );

    return ActorSearchResult(
      items: itemRows.map(ActorListItem.fromMap).toList(growable: false),
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
