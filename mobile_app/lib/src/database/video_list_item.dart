class VideoListItem {
  const VideoListItem({
    required this.code,
    required this.title,
    required this.author,
    required this.duration,
    required this.size,
    required this.storageLocation,
    required this.releaseDate,
    required this.maker,
    required this.publisher,
    required this.videoCategory,
    required this.enrichmentStatus,
  });

  final String code;
  final String title;
  final String author;
  final String duration;
  final String size;
  final String storageLocation;
  final String releaseDate;
  final String maker;
  final String publisher;
  final String videoCategory;
  final String enrichmentStatus;

  factory VideoListItem.fromMap(Map<String, Object?> row) {
    String readString(String key) => (row[key] as String? ?? '').trim();

    return VideoListItem(
      code: readString('code'),
      title: readString('display_title'),
      author: readString('author'),
      duration: readString('duration'),
      size: readString('size'),
      storageLocation: readString('storage_location'),
      releaseDate: readString('display_release_date'),
      maker: readString('maker'),
      publisher: readString('publisher'),
      videoCategory: readString('video_category'),
      enrichmentStatus: readString('enrichment_status'),
    );
  }
}
