"""The most suspicious moments, as pictures (Oct 25, Darpan's request): the faces a face check scored most likely to be
a swap, each saved with the frame it was cut from, so the person reviewing a case can see what the score saw.

Both face checks keep them. The recording check (chimera/detector.py) writes out/<case>/evidence_frames/; the live
check (scripts/live_check.py) writes <log>_frames/ next to its score log, and the Console can attach those to a case
(out/<case>/live_frames/). Pictures stay on this computer, in folders git ignores; nothing here sends them anywhere,
and the evidence lines the agents read do not change (the recording's frames are a pointer in evidence.json's data,
not text).

A folder holds manifest.json and two files per moment: m<tenths of a second>_face.png, the 256 x 256 crop the models
scored, and m<tenths of a second>_frame.jpg, the whole frame. Moments are at least MIN_GAP seconds apart, so five
pictures are five moments of the call, not one second five times. They show what the score is about; they do not
prove a fake on their own, and a person looks at them and decides.
"""

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

KEEP = 5                  # moments kept per check
MIN_GAP = 2.0             # seconds between kept moments
MANIFEST = "manifest.json"
# The only names this module writes (and the Console serves): m<tenths of a second>[_<copy tag>]_face.png or _frame.jpg
PICTURE = re.compile(r"^m\d{6,7}(?:_[0-9a-f]{8})?_(?:face\.png|frame\.jpg)$")
JPEG_QUALITY = 90
POOL = 50                 # candidate faces kept to choose from (TopFrames)


def clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _now(precise: bool = False) -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds" if precise else "seconds")


def _write(path: Path, data: bytes) -> None:
    """Write through a temporary file and a rename, so a reader never sees half a picture or half a manifest.
    Windows refuses the rename for a moment while another process has the old file open, so it tries again."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05)


def _remove(path: Path) -> bool:
    """Delete one of this module's files; False when Windows refuses because another program has it open."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@dataclass
class Moment:
    t: float                          # seconds into the recording or the live session
    score: float                      # this face's combined score (0 = most real-looking, 1)
    tie: float = 0.0                  # the models' mean P(fake): breaks ties above every reference real video
    face: bytes | None = None         # the 256 x 256 crop the models scored, as PNG
    frame: bytes | None = None        # the whole frame it was cut from, as JPEG
    box: tuple | None = None          # (center x, center y, face size) in the frame, in pixels
    extra: dict = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return f"m{int(round(self.t * 10)):06d}"

    def key(self) -> tuple:
        return (self.score, self.tie)


def encode_face(face) -> bytes:
    import cv2
    return cv2.imencode(".png", np.asarray(face))[1].tobytes()


def encode_frame(frame) -> bytes:
    import cv2
    return cv2.imencode(".jpg", np.asarray(frame), [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()


def choose(candidates, keep: int = KEEP, min_gap: float = MIN_GAP) -> list[Moment]:
    """The most suspicious moments by score: the highest-scoring face first, then each next-highest face that is
    min_gap or more from every one already chosen, until keep are chosen. (Oct 26 review: the first version kept
    one moment per stretch in time order, so a rising run of scores pushed out faces that qualified.)"""
    chosen = []
    for c in sorted(candidates, key=Moment.key, reverse=True):
        if all(abs(c.t - m.t) >= min_gap for m in chosen):
            chosen.append(c)
            if len(chosen) == keep:
                break
    return chosen


class TopFrames:
    """The `keep` most suspicious moments seen so far, at least `min_gap` seconds apart (choose()).

    Candidates are the `pool` highest-scoring faces seen, kept as encoded pictures (a few MB, not raw frames). With
    two checks a second, each chosen moment rules out at most seven nearby faces, so a pool of 50 makes the choice
    the same as over every face. With a folder and autosave (the live check), every change rewrites the folder at
    once, so a session that is stopped or crashes still leaves its pictures; the recording check chooses over all
    its faces itself and calls save(folder).
    """

    def __init__(self, folder=None, keep: int = KEEP, min_gap: float = MIN_GAP, meta: dict | None = None,
                 autosave: bool = False, pool: int = POOL):
        self.folder = Path(folder) if folder else None
        self.keep, self.min_gap, self.pool = keep, min_gap, max(pool, keep)
        self.meta = dict(meta or {})
        self.autosave = autosave and self.folder is not None
        self.candidates: list[Moment] = []
        self.moments: list[Moment] = []           # the chosen ones, highest score first
        self.created = _now()
        self._on_disk: dict[str, Moment] = {}     # stem -> the moment whose pictures are in self.folder

    def offer(self, t, score, face=None, frame=None, box=None, tie=0.0, extra=None) -> bool:
        """Consider one scored face. True when it is now one of the chosen moments. Its pictures are encoded when it
        enters the pool, so the caller may draw on its frame afterwards."""
        if self.keep <= 0 or score is None or not np.isfinite(score):
            return False
        new = Moment(float(t), float(score), float(tie or 0.0),
                     box=None if box is None else tuple(float(v) for v in box), extra=dict(extra or {}))
        if len(self.candidates) >= self.pool and new.key() <= min(c.key() for c in self.candidates):
            return False
        new.face = None if face is None else encode_face(face)
        new.frame = None if frame is None else encode_frame(frame)
        self.candidates.append(new)
        before = [id(m) for m in self.moments]
        self.moments = choose(self.candidates, self.keep, self.min_gap)
        if len(self.candidates) > self.pool:      # drop the lowest candidate that was not chosen
            spare = [c for c in self.candidates if all(c is not m for m in self.moments)]
            self.candidates.remove(min(spare, key=Moment.key))
        if self.autosave and [id(m) for m in self.moments] != before:
            self.save()
        return any(new is m for m in self.moments)

    def ranked(self) -> list[Moment]:
        return sorted(self.moments, key=Moment.key, reverse=True)

    def manifest(self) -> dict:
        return {**self.meta, "created": self.created, "updated": _now(precise=True), "keep": self.keep,
                "min_gap_s": self.min_gap,
                "moments": [{"rank": i, "t": round(m.t, 2), "clock": clock(m.t), "score": round(m.score, 4),
                             "face": f"{m.stem}_face.png" if m.face is not None else None,
                             "frame": f"{m.stem}_frame.jpg" if m.frame is not None else None,
                             "box": None if m.box is None else [round(v, 1) for v in m.box], **m.extra}
                            for i, m in enumerate(self.ranked(), 1)]}

    def save(self, folder=None) -> dict:
        """Write the chosen moments' pictures and manifest.json, and remove pictures of moments no longer chosen. A
        picture another program has open (the Console serving it) cannot be removed on Windows; it is left, unlisted,
        and removed at a later save."""
        folder = Path(folder) if folder else self.folder
        if folder is None:
            raise ValueError("no folder to save the evidence frames in")
        folder.mkdir(parents=True, exist_ok=True)
        incremental = folder == self.folder
        for m in self.moments:
            if incremental and self._on_disk.get(m.stem) is m:
                continue
            if m.face is not None:
                _write(folder / f"{m.stem}_face.png", m.face)
            if m.frame is not None:
                _write(folder / f"{m.stem}_frame.jpg", m.frame)
        chosen = {m.stem for m in self.moments}
        for p in folder.iterdir():
            if PICTURE.match(p.name) and p.name.split("_")[0] not in chosen:
                _remove(p)
        manifest = self.manifest()
        _write(folder / MANIFEST, json.dumps(manifest, indent=1).encode("utf-8"))
        if incremental:
            self._on_disk = {m.stem: m for m in self.moments}
        return manifest


def read_manifest(folder) -> dict | None:
    """A folder's manifest, or None when there is none (or it cannot be read)."""
    path = Path(folder) / MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear(folder) -> None:
    """Remove a folder's pictures and manifest: only the files this module writes, and the folder if it is then
    empty. Never raises: a file another program has open stays, listed nowhere."""
    folder = Path(folder)
    if not folder.is_dir():
        return
    for p in folder.iterdir():
        if p.is_file() and (PICTURE.match(p.name) or p.name == MANIFEST or p.name.endswith(".tmp")):
            _remove(p)
    try:
        folder.rmdir()
    except OSError:
        pass                                      # something is still in it: leave it


def copy(src, dst, extra: dict | None = None) -> dict | None:
    """Copy one folder's moments into another (the Console attaching a live session's pictures to a case), replacing
    what was there, all or nothing. The new pictures get names of their own (a tag per copy), so no file that may be
    open is ever overwritten; only moments whose pictures all came through are listed; the manifest is replaced in
    one step at the end, and only then are the old pictures removed (any still open stay, unlisted). Until that step
    the case keeps its earlier pictures whole (Oct 26 reviews: clearing first, or overwriting a picture the Console
    was serving, could leave the case with none). Returns the new manifest, or None when nothing could be copied."""
    import shutil
    src, dst = Path(src), Path(dst)
    manifest = read_manifest(src)
    if manifest is None:
        return None
    dst.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    moments, written = [], []
    for m in manifest.get("moments", []):
        names = {k: m.get(k) for k in ("face", "frame") if m.get(k)}
        if not names or not all(PICTURE.match(str(n)) for n in names.values()):
            continue
        ours = {k: n.replace("_", f"_{tag}_", 1) for k, n in names.items()}
        try:
            for k, n in names.items():
                shutil.copyfile(src / n, dst / ours[k])
        except OSError:                           # dropped or locked while we copied: leave this moment out
            for n in ours.values():
                _remove(dst / n)
            continue
        written += ours.values()
        moments.append({**m, **ours, "rank": len(moments) + 1})
    if not moments:
        return None
    manifest = {**manifest, "moments": moments, **(extra or {})}
    try:
        _write(dst / MANIFEST, json.dumps(manifest, indent=1).encode("utf-8"))
    except OSError:
        for n in written:                         # the earlier manifest still stands: take ours back out
            _remove(dst / n)
        raise
    for p in dst.iterdir():
        if PICTURE.match(p.name) and p.name not in written:
            _remove(p)
    return manifest
