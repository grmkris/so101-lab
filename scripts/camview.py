"""Live camera preview. Usage: python ../camview.py [index]   (press Q to quit)"""
import sys, cv2

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
cap = cv2.VideoCapture(idx)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
print(f"Live view of camera {idx}. Click the window, press Q to quit.")
win = f"cam {idx} - press Q to quit"
while True:
    ok, frame = cap.read()
    if not ok:
        continue
    cv2.imshow(win, frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break
cap.release()
cv2.destroyAllWindows()
