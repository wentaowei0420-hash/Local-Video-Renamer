class DatabaseStatus {
  const DatabaseStatus({
    required this.directoryLabel,
    required this.databasePath,
    required this.exists,
    this.sizeBytes,
    this.modifiedAt,
  });

  final String directoryLabel;
  final String databasePath;
  final bool exists;
  final int? sizeBytes;
  final DateTime? modifiedAt;

  String get sizeLabel {
    final size = sizeBytes;
    if (size == null) {
      return '未检测到';
    }
    if (size < 1024) {
      return '$size B';
    }
    if (size < 1024 * 1024) {
      return '${(size / 1024).toStringAsFixed(1)} KB';
    }
    if (size < 1024 * 1024 * 1024) {
      return '${(size / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(size / (1024 * 1024 * 1024)).toStringAsFixed(2)} GB';
  }

  String get modifiedLabel {
    final value = modifiedAt;
    if (value == null) {
      return '未检测到';
    }
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    final hour = value.hour.toString().padLeft(2, '0');
    final minute = value.minute.toString().padLeft(2, '0');
    return '${value.year}-$month-$day $hour:$minute';
  }
}
