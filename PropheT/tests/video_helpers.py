"""Test support: tiny videos with a bright square standing in for a face, and a face finder that finds it.

The square's brightness is its "confidence", so a dim square plays a face the finder is unsure about.
Real video files and the real cutting code get exercised; only the MediaPipe model is swapped out.
"""
import cv2
import numpy as np

STEADY = (110, 50, 60, 250)        # x, y, side, gray: a bright square that stays put
SIZE = (320, 180)                  # width, height of the test videos


def write_clip(path, frames=32, face=lambda n: STEADY, fps=15):
    """Write a small video. face(n) says where the square is in frame n, or None for an empty frame."""
    fourcc = cv2.VideoWriter_fourcc(*("MJPG" if str(path).endswith(".avi") else "mp4v"))
    writer = cv2.VideoWriter(str(path), fourcc, fps, SIZE)
    for n in range(frames):
        frame = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
        square = face(n)
        if square:
            x, y, side, gray = square
            frame[y:y + side, x:x + side] = gray
        writer.write(frame)
    writer.release()
    return path


class FakeJudge:
    """Stand-in for the Qwen model. Before an adapter is added it answers 0.5 for everything (a coin flip).
    After, it says 0.9 for pictures whose path mentions "synthesis" or "fake" and 0.1 for all others."""

    def __init__(self):
        self.adapter = None
        self.scored = 0

    def add_adapter(self, path):
        self.adapter = path

    def score(self, pictures):
        self.scored += len(pictures)
        if self.adapter is None:
            return np.full(len(pictures), 0.5)
        return np.array([0.9 if ("synthesis" in str(p) or "fake" in str(p)) else 0.1 for p in pictures])


def square_finder(frame):
    """Stand-in for the MediaPipe finder: (center x, center y, size, confidence) of the bright square, or None."""
    lit = frame.max(axis=2) > 60
    if not lit.any():
        return None
    ys, xs = np.nonzero(lit)
    width, height = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    return (xs.min() + width / 2, ys.min() + height / 2, max(width, height), frame[lit].mean() / 255)
