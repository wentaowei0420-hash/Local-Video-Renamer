import 'package:flutter/material.dart';

enum LibraryTone { video, actor, prefix }

class AppDesign {
  const AppDesign._();

  static const Color background = Color(0xFFF6F1EA);
  static const Color backgroundStrong = Color(0xFFEDE4D9);
  static const Color surface = Color(0xFFFFFCF8);
  static const Color surfaceMuted = Color(0xFFF7F0E7);
  static const Color border = Color(0xFFE3D6C8);
  static const Color borderStrong = Color(0xFFD0BEAA);
  static const Color ink = Color(0xFF251D1A);
  static const Color inkMuted = Color(0xFF6D6259);
  static const Color indigo = Color(0xFF4F46E5);
  static const Color indigoSoft = Color(0xFFE9E7FF);
  static const Color teal = Color(0xFF0F766E);
  static const Color tealSoft = Color(0xFFDCF7F1);
  static const Color amber = Color(0xFFB45309);
  static const Color amberSoft = Color(0xFFF9E7C8);

  static const double cardRadius = 30;
  static const double panelRadius = 26;
  static const double chipRadius = 999;

  static const List<BoxShadow> softShadow = [
    BoxShadow(
      color: Color(0x120F172A),
      blurRadius: 26,
      offset: Offset(0, 14),
    ),
  ];

  static const LinearGradient appBackground = LinearGradient(
    begin: Alignment.topCenter,
    end: Alignment.bottomCenter,
    colors: [
      Color(0xFFF9F4EE),
      Color(0xFFF6F1EA),
      Color(0xFFF1E9DF),
    ],
  );

  static List<Color> heroGradient(LibraryTone tone) {
    switch (tone) {
      case LibraryTone.actor:
        return const [Color(0xFF1F3B37), Color(0xFF3C7268)];
      case LibraryTone.prefix:
        return const [Color(0xFF2D2F55), Color(0xFF5960A9)];
      case LibraryTone.video:
        return const [Color(0xFF332620), Color(0xFF8E5E48)];
    }
  }

  static Color toneForeground(LibraryTone tone) {
    switch (tone) {
      case LibraryTone.actor:
        return const Color(0xFF1E5C52);
      case LibraryTone.prefix:
        return const Color(0xFF4C45A0);
      case LibraryTone.video:
        return const Color(0xFF8B4A34);
    }
  }

  static Color toneSurface(LibraryTone tone) {
    switch (tone) {
      case LibraryTone.actor:
        return const Color(0xFFE7F4F0);
      case LibraryTone.prefix:
        return const Color(0xFFEEEBFF);
      case LibraryTone.video:
        return const Color(0xFFF8ECE4);
    }
  }
}
