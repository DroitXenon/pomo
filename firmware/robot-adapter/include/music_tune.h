// "Pomo Theme": a short original tune for the robot's music page, played as
// square-wave tones when no include/music_user.h has been generated.
#pragma once
#include <Arduino.h>

struct TuneNote {
  uint16_t frequency;  // Hz; 0 is a rest.
  uint8_t eighths;     // Length in eighth notes.
};

constexpr const char* TUNE_TITLE = "Pomo Theme";
constexpr uint32_t TUNE_EIGHTH_MS = 210;  // About 143 beats per minute.

namespace tune {
constexpr uint16_t R = 0, G4 = 392, A4 = 440, B4 = 494, C5 = 523, D5 = 587, E5 = 659,
                   F5 = 698, G5 = 784, A5 = 880, B5 = 988, C6 = 1047;
}

constexpr TuneNote TUNE[] = {
  // A: rising and bright.
  {tune::C5, 1}, {tune::E5, 1}, {tune::G5, 1}, {tune::E5, 1},
  {tune::F5, 1}, {tune::A5, 1}, {tune::G5, 2},
  {tune::E5, 1}, {tune::G5, 1}, {tune::C6, 1}, {tune::B5, 1},
  {tune::A5, 2}, {tune::G5, 2},
  // B: stepping home.
  {tune::F5, 1}, {tune::E5, 1}, {tune::D5, 1}, {tune::E5, 1},
  {tune::F5, 1}, {tune::G5, 1}, {tune::A5, 2},
  {tune::G5, 1}, {tune::F5, 1}, {tune::E5, 1}, {tune::D5, 1},
  {tune::E5, 2}, {tune::R, 2},
  // A again.
  {tune::C5, 1}, {tune::E5, 1}, {tune::G5, 1}, {tune::E5, 1},
  {tune::F5, 1}, {tune::A5, 1}, {tune::G5, 2},
  {tune::E5, 1}, {tune::G5, 1}, {tune::C6, 1}, {tune::B5, 1},
  {tune::A5, 2}, {tune::C6, 2},
  // Ending: down to the low G, then home on C.
  {tune::B5, 1}, {tune::A5, 1}, {tune::G5, 1}, {tune::E5, 1},
  {tune::D5, 1}, {tune::B4, 1}, {tune::G4, 2},
  {tune::A4, 1}, {tune::B4, 1}, {tune::D5, 1}, {tune::E5, 1},
  {tune::C5, 4},
};
