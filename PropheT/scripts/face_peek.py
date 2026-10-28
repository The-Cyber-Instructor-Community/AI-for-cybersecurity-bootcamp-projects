# face_peek.py: find the face in one video frame and save it as a crop
import sys
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

video = Path(sys.argv[1])
cap = cv2.VideoCapture(str(video))
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cap.set(cv2.CAP_PROP_POS_FRAMES, n // 2)              # jump to the middle frame
ok, frame = cap.read()
if not ok:
    sys.exit("Could not read a frame")
print("frames:", n, "| frame size (h, w, colors):", frame.shape)

detector = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
    base_options=mp_tasks.BaseOptions(model_asset_path="models/blaze_face_short_range.tflite")))
rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)          # OpenCV stores colors as BGR; MediaPipe wants RGB
faces = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)).detections
detector.close()                                      # free the model now, so Python exits cleanly
if not faces:
    sys.exit("No face found")
box = faces[0].bounding_box
print("faces:", len(faces), "| box x, y, w, h:", box.origin_x, box.origin_y, box.width, box.height,
      "| confidence:", round(faces[0].categories[0].score, 2))

# Grow the box by 30%: a swap is blended in around the face's edges, so keep them in the crop
cx, cy = box.origin_x + box.width / 2, box.origin_y + box.height / 2
side = int(max(box.width, box.height) * 1.3)
x0, y0 = max(int(cx - side / 2), 0), max(int(cy - side / 2), 0)
crop = cv2.resize(frame[y0:y0 + side, x0:x0 + side], (256, 256))   # every face gets the same size

cv2.rectangle(frame, (box.origin_x, box.origin_y),
              (box.origin_x + box.width, box.origin_y + box.height), (0, 255, 0), 2)
cv2.imwrite(f"data/peek/{video.stem}_frame.png", frame)
cv2.imwrite(f"data/peek/{video.stem}_crop.png", crop)
print("saved", f"data/peek/{video.stem}_frame.png and _crop.png")