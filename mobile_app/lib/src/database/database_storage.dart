import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'database_status.dart';

class DatabaseStorage {
  const DatabaseStorage();

  static const String databaseFileName = 'video_database.db';

  Future<DatabaseStatus> inspectStatus() async {
    final location = await _resolvePreferredDirectory();
    final file = File(p.join(location.directory.path, databaseFileName));
    final exists = await file.exists();

    if (!exists) {
      return DatabaseStatus(
        directoryLabel: location.label,
        databasePath: file.path,
        exists: false,
      );
    }

    final stat = await file.stat();
    return DatabaseStatus(
      directoryLabel: location.label,
      databasePath: file.path,
      exists: true,
      sizeBytes: stat.size,
      modifiedAt: stat.modified,
    );
  }

  Future<_DatabaseDirectory> _resolvePreferredDirectory() async {
    final external = await getExternalStorageDirectory();
    if (external != null) {
      await external.create(recursive: true);
      return _DatabaseDirectory(
        directory: external,
        label: 'Android 专属外部目录',
      );
    }

    final documents = await getApplicationDocumentsDirectory();
    await documents.create(recursive: true);
    return _DatabaseDirectory(
      directory: documents,
      label: '应用内部文档目录',
    );
  }
}

class _DatabaseDirectory {
  const _DatabaseDirectory({
    required this.directory,
    required this.label,
  });

  final Directory directory;
  final String label;
}
