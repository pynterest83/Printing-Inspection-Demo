# Demo Plan — Hệ thống giám sát lỗi in màng mỏng 5 luồng

## 1. Mục tiêu

Dựng một bản demo end-to-end mô phỏng hệ thống kiểm tra lỗi in trên màng mỏng với:

- 01 nguồn dữ liệu giả lập thay cho line-scan camera.
- 05 lane chạy song song.
- Tốc độ dây chuyền logic: **200–300 m/phút**.
- Ứng dụng inspection đọc stream, xử lý frame, phát hiện lỗi và sinh event.
- Frontend hiển thị:
  - Live view 5 lane.
  - Speed.
  - Position.
  - Total / Good / Bad length.
  - Bad ratio.
  - Defect list.
  - Bounding box.
  - Alarm.
- Thiết kế sao cho sau này có thể thay `MockSource` bằng camera thật mà không cần viết lại frontend/backend.

> Mục tiêu của demo không phải mô phỏng chính xác vật lý của line-scan camera, mà là mô phỏng đúng **luồng dữ liệu và hành vi hệ thống**.

---

# 2. Kiến trúc tổng thể

```text
                         DEMO

                  Synthetic / Mock Roll
                           │
                           ▼
                    MockImageSource
                           │
                           ▼
               ┌─────────────────────┐
               │   Inspection App    │
               │                     │
               │ Frame acquisition   │
               │ Lane split          │
               │ Detection           │
               │ Defect tracking     │
               │ Roll tracking       │
               │ Alarm logic         │
               └──────────┬──────────┘
                          │
                  REST + WebSocket
                          │
                          ▼
               ┌─────────────────────┐
               │      Frontend       │
               │                     │
               │ Live View           │
               │ Defect List         │
               │ Speed / Position    │
               │ Good / Bad          │
               │ Alarm               │
               └─────────────────────┘
```

Kiến trúc production sau này:

```text
MockImageSource  ─────┐
                      ├──> Inspection Pipeline ──> API ──> Frontend
LineScanCameraSource ─┘
```

---

# 3. Công nghệ đề xuất

## Backend / Inspection App

- Python 3.11+
- FastAPI
- Uvicorn
- OpenCV
- NumPy
- Pillow
- WebSocket
- Pydantic
- SQLite cho MVP

Optional:

- YOLO / PyTorch / ONNX Runtime
- PostgreSQL
- Redis
- TensorRT

## Frontend

Khuyến nghị:

- React
- Vite
- TypeScript
- TailwindCSS
- Zustand hoặc React Context
- Native WebSocket API

---

# 4. Cấu trúc repository

```text
printing-inspection-demo/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │   ├── routes.py
│   │   │   └── websocket.py
│   │   │
│   │   ├── sources/
│   │   │   ├── base.py
│   │   │   ├── mock_source.py
│   │   │   └── camera_source.py
│   │   │
│   │   ├── vision/
│   │   │   ├── lane_split.py
│   │   │   ├── detector.py
│   │   │   ├── mock_detector.py
│   │   │   └── drawing.py
│   │   │
│   │   ├── services/
│   │   │   ├── inspection.py
│   │   │   ├── roll_manager.py
│   │   │   ├── alarm_manager.py
│   │   │   └── defect_store.py
│   │   │
│   │   ├── models/
│   │   │   ├── telemetry.py
│   │   │   └── defect.py
│   │   │
│   │   └── config.py
│   │
│   ├── data/
│   │   ├── master_roll/
│   │   ├── defects/
│   │   └── annotations/
│   │
│   ├── scripts/
│   │   ├── prepare_taktpixel.py
│   │   ├── create_synthetic_roll.py
│   │   └── inspect_dataset.py
│   │
│   ├── config.yaml
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LiveView.tsx
│   │   │   ├── DefectList.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   ├── LaneStatus.tsx
│   │   │   └── AlarmBanner.tsx
│   │   ├── hooks/
│   │   │   └── useInspectionSocket.ts
│   │   ├── pages/
│   │   │   └── Dashboard.tsx
│   │   ├── api/
│   │   └── App.tsx
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml
└── README.md
```

---

# 5. Nguồn dữ liệu

## 5.1 Dataset chính

Sử dụng:

**Taktpixel2025PD-CD**

Repository:

https://github.com/taktpixel/Taktpixel2025PD-CD

Dataset có ba thành phần:

```text
A/      reference / master image
B/      defective image
OUT/    defect mask
```

Các loại defect có thể dùng:

```text
blackspot
colorshift
friction
hair
line
pinhole
```

Mapping sang demo:

```text
blackspot   -> Dark Spot
colorshift  -> Color Shift
friction    -> Missing Ink
hair        -> Contamination
line        -> Streak
pinhole     -> Light Spot / Missing Print
```

## 5.2 Background tốt nhất

Ưu tiên xin khách:

```text
good_package.png
```

hoặc:

```text
artwork.pdf
```

hoặc 5–10 ảnh sản phẩm GOOD.

Nếu chưa có, dùng một artwork mock đơn giản.

---

# 6. Chiến lược tạo mock data

Không cần sinh 10.000 frame độc lập.

Tạo một **master roll dài**:

```text
                       moving direction
                              ↓

┌────────┬────────┬────────┬────────┬────────┐
│ Lane 1 │ Lane 2 │ Lane 3 │ Lane 4 │ Lane 5 │
│        │        │        │        │        │
│ GOOD   │ GOOD   │ GOOD   │ GOOD   │ GOOD   │
│        │        │        │   ●    │        │
│        │        │        │        │        │
│ GOOD   │ GOOD   │ GOOD   │ GOOD   │ GOOD   │
│        │   │    │        │        │        │
│        │   │    │        │        │        │
└────────┴────────┴────────┴────────┴────────┘
```

Sau đó `MockImageSource` chỉ crop một cửa sổ đang di chuyển.

---

# 7. Kích thước mock image đề xuất

Không cần theo resolution camera thật.

MVP:

```yaml
frame:
  width: 1920
  height: 600

lanes:
  count: 5

master_roll:
  width: 1920
  height: 30000
```

Tương đương:

```text
lane_width ≈ 1920 / 5
           ≈ 384 px
```

Có thể chừa gap giữa các lane.

---

# 8. Tạo master roll

## 8.1 Tạo tile GOOD

Ví dụ:

```text
good_tile.png

┌─────────────────┐
│                 │
│   PRODUCT LOGO  │
│                 │
│   product name  │
│                 │
└─────────────────┘
```

Lặp dọc:

```text
GOOD TILE
GOOD TILE
GOOD TILE
GOOD TILE
...
```

rồi replicate ngang thành 5 lane.

## 8.2 Inject defect

Sinh một `scenario.json` deterministic:

```json
[
  {
    "position_m": 20.0,
    "lane": 2,
    "type": "dark_spot"
  },
  {
    "position_m": 45.0,
    "lane": 4,
    "type": "streak"
  },
  {
    "position_m": 70.0,
    "lane": 1,
    "type": "missing_ink"
  },
  {
    "position_m": 100.0,
    "lane": 5,
    "type": "color_shift"
  }
]
```

Script:

```text
create_synthetic_roll.py
```

sẽ:

1. Tạo background GOOD.
2. Chọn defect patch.
3. Chọn lane.
4. Chọn tọa độ.
5. Blend defect vào background.
6. Sinh bbox.
7. Ghi annotation.
8. Save `master_roll.jpg`.
9. Save `annotations.json`.

---

# 9. Annotation format

Dùng format riêng đơn giản:

```json
{
  "roll_id": "ROLL-DEMO-001",
  "width_px": 1920,
  "height_px": 30000,

  "defects": [
    {
      "id": "DEF-00001",
      "type": "dark_spot",
      "lane": 2,

      "bbox": {
        "x": 520,
        "y": 4200,
        "w": 35,
        "h": 30
      },

      "position_m": 35.2,

      "measurement": {
        "area_mm2": 1.42
      },

      "confidence": 0.96
    }
  ]
}
```

`confidence` trong demo có thể mock.

---

# 10. Mock camera abstraction

Tạo interface:

```python
from abc import ABC, abstractmethod


class ImageSource(ABC):

    @abstractmethod
    def read(self):
        ...

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    def stop(self):
        ...
```

Mock:

```python
class MockImageSource(ImageSource):

    def __init__(self, image, frame_height):
        self.image = image
        self.frame_height = frame_height
        self.offset = 0

    def read(self):
        frame = self.image[
            self.offset:self.offset + self.frame_height
        ]

        self.offset += 10

        if self.offset + self.frame_height >= self.image.shape[0]:
            self.offset = 0

        return frame
```

Sau này:

```python
class BaslerLineScanSource(ImageSource):
    ...
```

---

# 11. Không map FPS trực tiếp sang m/min

Tách:

```text
visual frame rate
```

và:

```text
logical machine speed
```

Ví dụ:

```yaml
mock:
  fps: 30

machine:
  min_speed_m_min: 200
  max_speed_m_min: 300
  initial_speed_m_min: 240
```

Position:

```python
position_m += speed_m_min / 60.0 * delta_time
```

Ví dụ 240 m/min:

```text
240 / 60 = 4 m/s
```

Sau 100 ms:

```text
position += 0.4 m
```

---

# 12. Speed simulator

Không dùng:

```python
random.randint(200, 300)
```

ở mỗi frame.

Dùng target speed:

```python
speed += (target_speed - speed) * 0.02
```

Kịch bản:

```text
0–20 s      200 -> 230
20–60 s     ~240
60–100 s    ~260
100–140 s   ~290
140–170 s   ~250
```

Có thể cộng noise nhỏ:

```python
noise = random.uniform(-1.0, 1.0)
```

---

# 13. Lane split

```python
def split_lanes(frame, lane_count=5):
    h, w = frame.shape[:2]

    lane_width = w // lane_count

    return [
        frame[:, i * lane_width:(i + 1) * lane_width]
        for i in range(lane_count)
    ]
```

Sau này có thể thay bằng ROI config.

---

# 14. Detector — Phase 1

MVP **không cần AI thật**.

`MockDetector` đọc annotation và kiểm tra defect nào nằm trong viewport hiện tại:

```text
master y = 10000
viewport:

10000
  ↓
┌─────────────┐
│             │
│ defect      │
│             │
└─────────────┘
  ↑
10600
```

Nếu bbox của defect intersect viewport:

```python
if defect_y < viewport_bottom and defect_bottom > viewport_top:
    emit(defect)
```

Như vậy:

- Bounding box luôn chính xác.
- Demo deterministic.
- Không phụ thuộc accuracy model.
- Frontend/app pipeline hoàn chỉnh.

---

# 15. Detector — Phase 2

Sau khi MVP chạy:

```text
frame
  ↓
YOLO / change detection model
  ↓
detections
```

Có thể triển khai:

```python
class Detector:

    def detect(self, frame):
        return [
            Defect(...)
        ]
```

để `MockDetector` và `RealDetector` chung interface.

---

# 16. Defect event model

```python
class DefectEvent(BaseModel):
    id: str
    timestamp: datetime

    roll_id: str

    lane_id: int
    position_m: float

    defect_type: str
    defect_name: str

    confidence: float

    bbox: dict

    severity: str

    area_mm2: float | None = None
    length_mm: float | None = None

    image_url: str | None = None
```

WebSocket JSON:

```json
{
  "type": "defect",

  "data": {
    "id": "DEF-00014",
    "timestamp": "2026-09-25T14:30:15+07:00",

    "roll_id": "ROLL-DEMO-001",

    "lane_id": 3,
    "position_m": 352.42,

    "defect_type": "dark_spot",
    "defect_name": "Dark Spot",

    "confidence": 0.96,

    "bbox": {
      "x": 1220,
      "y": 151,
      "w": 32,
      "h": 29
    },

    "severity": "medium",

    "area_mm2": 1.76
  }
}
```

---

# 17. Telemetry model

Gửi 5–10 Hz.

```json
{
  "type": "telemetry",

  "data": {
    "machine_status": "RUNNING",

    "speed_m_min": 254.2,
    "position_m": 352.42,

    "roll": {
      "roll_id": "ROLL-DEMO-001",
      "total_m": 352.42,
      "good_m": 347.30,
      "bad_m": 5.12,
      "bad_ratio": 1.45
    },

    "lanes": [
      {"lane_id": 1, "status": "OK"},
      {"lane_id": 2, "status": "OK"},
      {"lane_id": 3, "status": "NG"},
      {"lane_id": 4, "status": "OK"},
      {"lane_id": 5, "status": "OK"}
    ]
  }
}
```

---

# 18. REST API

Minimum:

```text
GET /health

GET /api/status

GET /api/defects

GET /api/defects/{id}

GET /api/live/frame.jpg

POST /api/demo/start

POST /api/demo/stop

POST /api/demo/reset
```

Optional:

```text
POST /api/demo/inject-defect
POST /api/demo/set-speed
```

---

# 19. WebSocket API

```text
WS /ws/inspection
```

Messages:

```text
telemetry
defect
alarm
machine_status
```

Ví dụ frontend:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/inspection");

ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);

    switch (msg.type) {
        case "telemetry":
            updateTelemetry(msg.data);
            break;

        case "defect":
            addDefect(msg.data);
            break;

        case "alarm":
            showAlarm(msg.data);
            break;
    }
};
```

---

# 20. Live image transport

MVP đơn giản:

```text
GET /api/live/frame.jpg
```

Frontend refresh khoảng:

```text
5–10 FPS
```

Không cần stream full 30 FPS ngay.

Nếu muốn mượt hơn:

```text
MJPEG
```

hoặc WebRTC.

Không gửi raw base64 frame qua WebSocket nếu không cần.

---

# 21. Roll manager

State:

```python
class RollState:

    roll_id: str

    total_m: float
    good_m: float
    bad_m: float

    position_m: float

    speed_m_min: float
```

Update:

```python
delta_m = speed_m_min / 60 * dt

total_m += delta_m
position_m += delta_m
```

---

# 22. Bad length cho MVP

Tạm define:

> Nếu tại một vị trí có ít nhất một lane NG thì đoạn đó được tính là bad roll length.

```python
if any_lane_bad:
    bad_m += delta_m
else:
    good_m += delta_m
```

```python
bad_ratio = bad_m / total_m * 100
```

**Phải confirm lại với khách**, vì nếu 5 lane sau đó trở thành 5 sản phẩm độc lập thì có thể cần dùng lane-meter.

---

# 23. Alarm logic

Config:

```yaml
alarm:
  consecutive_defects: 5

  continuous_defect:
    warning_length_m: 1
    stop_length_m: 3

  bad_ratio:
    warning_percent: 3
```

States:

```text
NORMAL
  ↓
WARNING
  ↓
ALARM
  ↓
PLC_STOP (mock)
```

WebSocket:

```json
{
  "type": "alarm",

  "data": {
    "level": "warning",
    "message": "Continuous streak detected",
    "lane_id": 4,
    "position_m": 425.2
  }
}
```

---

# 24. Defect history database

MVP dùng SQLite.

Table:

```sql
CREATE TABLE defects (
    id TEXT PRIMARY KEY,

    timestamp DATETIME,

    roll_id TEXT,

    lane_id INTEGER,

    position_m REAL,

    defect_type TEXT,

    confidence REAL,

    severity TEXT,

    area_mm2 REAL,

    length_mm REAL,

    image_path TEXT
);
```

---

# 25. Frontend layout

Mimic style của máy inspection thực tế.

```text
┌────────────────────────────────────────────────────────────┐
│ INSPECTING ●   254 m/min   Total 352m   Bad Ratio 1.45%   │
├───────────────────────────────────┬────────────────────────┤
│                                   │ DEFECT LIST            │
│                                   │                        │
│          FULL LIVE VIEW           │ Dark Spot              │
│                                   │ Lane 3                 │
│       L1 L2 L3 L4 L5              │ 1.76 mm²               │
│                                   │ 352.42 m               │
│                                   ├────────────────────────┤
│                                   │ Streak                 │
│                                   │ Lane 4                 │
├─────────────────┬─────────────────┤ ...                    │
│ LIVE DEFECT     │ STANDARD/GOOD   │                        │
│                 │                 │                        │
├─────────────────┴─────────────────┴────────────────────────┤
│ Roll ID | Position | Total | Good | Bad | Speed | Status   │
└────────────────────────────────────────────────────────────┘
```

---

# 26. Frontend components

## StatusBar

Hiển thị:

```text
INSPECTING
Speed
Position
Total
Bad Ratio
```

## LiveView

Hiển thị full frame 5 lane.

Overlay:

```text
bbox
label
confidence
lane
```

## DefectList

Card:

```text
Dark Spot

Lane 3
352.42 m
1.76 mm²
96%
14:32:04
```

## LaneStatus

```text
L1  OK
L2  OK
L3  NG
L4  OK
L5  OK
```

## AlarmBanner

```text
WARNING

Continuous Streak
Lane 4
Length: 1.8 m
```

---

# 27. Config demo

`config.yaml`

```yaml
machine:
  initial_speed_m_min: 230
  min_speed_m_min: 200
  max_speed_m_min: 300

lanes:
  count: 5

mock:
  fps: 30
  loop: true

telemetry:
  hz: 10

frame:
  width: 1920
  height: 600

master_roll:
  path: data/master_roll/master_roll.jpg

annotations:
  path: data/annotations/annotations.json

defects:
  confidence:
    min: 0.85
    max: 0.99

alarm:
  consecutive_defects: 5

  continuous_defect:
    warning_length_m: 1.0
    stop_length_m: 3.0

  bad_ratio_warning_percent: 3.0
```

---

# 28. Demo scenario

Nên deterministic.

Ví dụ 3 phút:

```text
00:00     Start

00:10     Machine ramp 200 -> 230 m/min

00:20     Lane 2
          Dark Spot

00:35     Lane 5
          Pinhole

00:50     Lane 1
          Missing Ink

01:05     Lane 3
          Color Shift

01:20     Lane 4
          Streak

01:40     Multiple Dark Spots

02:00     Long Streak
          Warning

02:10     Streak > threshold
          Alarm

02:20     Mock PLC Stop

02:30     Operator Reset

02:40     Resume

03:00     End
```

---

# 29. Phase triển khai

## Phase 0 — Bootstrap

### Task

- Tạo repo.
- Setup backend.
- Setup frontend.
- Docker Compose.

### Done khi

```text
GET /health -> 200
frontend mở được
```

---

## Phase 1 — Mock stream

### Task

- Tạo artwork GOOD.
- Tạo master roll 5 lane.
- Implement `MockImageSource`.
- Crop frame liên tục.
- Expose `/api/live/frame.jpg`.

### Done khi

Frontend nhìn thấy màng chạy liên tục.

---

## Phase 2 — Mock detection

### Task

- Tạo annotations.
- Implement `MockDetector`.
- Convert global bbox -> viewport bbox.
- Draw bbox.
- Sinh defect event.

### Done khi

Defect xuất hiện đúng vị trí trên ảnh.

---

## Phase 3 — Telemetry

### Task

Implement:

```text
speed
position
total
good
bad
bad ratio
lane status
```

### Done khi

Dashboard update realtime.

---

## Phase 4 — WebSocket

### Task

Implement:

```text
/ws/inspection
```

Push:

```text
telemetry
defect
alarm
```

### Done khi

Không cần refresh browser mà data vẫn update.

---

## Phase 5 — Defect history

### Task

- SQLite.
- Save defects.
- `/api/defects`.
- Defect cards.

### Done khi

Click defect -> xem thumbnail + metadata.

---

## Phase 6 — Alarm

### Task

- Continuous defect tracking.
- Consecutive defects.
- Bad ratio.
- Mock PLC state.

### Done khi

Demo được:

```text
NORMAL -> WARNING -> ALARM
```

---

## Phase 7 — UI polish

### Task

- Layout giống industrial HMI.
- Full screen.
- Big fonts.
- High contrast.
- Minimal animation.
- Status color.
- Defect thumbnail grid.

---

# 30. MVP timeline đề xuất

Nếu một người implement:

## Day 1

```text
AM
- setup project
- mock image generator
- master roll
- mock source

PM
- FastAPI
- live frame
- telemetry
- websocket
```

## Day 2

```text
AM
- React dashboard
- live view
- stats
- defect list

PM
- alarm
- defect history
- styling
- scripted demo scenario
```

## Day 3 nếu có

```text
- polish
- integrate artwork khách
- add real detector
- Docker
- run full demo rehearsal
```

---

# 31. Requirements backend

`requirements.txt`

```text
fastapi
uvicorn[standard]
opencv-python
numpy
pillow
pydantic
pyyaml
websockets
sqlalchemy
```

Optional:

```text
ultralytics
onnxruntime-gpu
```

---

# 32. Local commands

Backend:

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Frontend:

```bash
cd frontend

npm install
npm run dev
```

---

# 33. Docker Compose target

```yaml
services:

  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend/data:/app/data

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
```

---

# 34. Những thứ KHÔNG nên làm ở MVP

Không cần ngay:

- TensorRT.
- GPU inference optimization.
- Kafka.
- Kubernetes.
- PostgreSQL.
- Redis.
- PLC thật.
- Basler SDK thật.
- 60 FPS frontend.
- Accuracy benchmark.
- Calibration mm/pixel chính xác.

MVP cần chứng minh:

```text
stream
→ inspection
→ defect
→ position
→ alarm
→ dashboard
```

---

# 35. Những dữ liệu cần hỏi khách

Trước khi production hóa phải confirm:

1. 5 lane là 5 sản phẩm độc lập hay 5 vùng inspection?
2. Chiều rộng toàn web bao nhiêu mm?
3. Chiều rộng mỗi lane?
4. Defect nhỏ nhất phải phát hiện?
5. Sai lệch màu tối đa?
6. Các loại defect chính xác?
7. Severity của từng defect?
8. Điều kiện warning?
9. Điều kiện stop PLC?
10. Cách tính bad ratio?
11. Camera/lens/lighting hiện tại?
12. PLC hãng gì?
13. Encoder resolution?
14. Yêu cầu lưu ảnh bao lâu?
15. Line speed thực tế min/max?
16. Có artwork/reference image chuẩn hay không?

---

# 36. Điểm chuyển sang production

Giữ nguyên:

```text
Frontend
REST API
WebSocket schema
Defect model
Roll manager
Alarm manager
Database schema
```

Thay:

```text
MockImageSource
        ↓
LineScanCameraSource
```

và:

```text
MockDetector
        ↓
RealDetector
```

Kiến trúc mong muốn:

```python
source = create_source(config)
detector = create_detector(config)

inspection = InspectionService(
    source=source,
    detector=detector,
)
```

Config demo:

```yaml
source:
  type: mock

detector:
  type: mock
```

Production:

```yaml
source:
  type: basler

detector:
  type: tensorrt
```

---

# 37. Definition of Done cho demo

Demo được coi là hoàn thành khi:

- [ ] Có stream giả lập 5 lane.
- [ ] Stream chạy liên tục.
- [ ] Speed nằm trong 200–300 m/min.
- [ ] Position tăng đúng theo speed và thời gian.
- [ ] Có ít nhất 5 loại defect.
- [ ] Bounding box hiển thị trên live image.
- [ ] Defect list cập nhật realtime.
- [ ] Mỗi defect có lane.
- [ ] Mỗi defect có position theo mét.
- [ ] Có confidence.
- [ ] Có defect thumbnail.
- [ ] Có Total / Good / Bad.
- [ ] Có Bad Ratio.
- [ ] Có lane status.
- [ ] Có Warning.
- [ ] Có Alarm.
- [ ] Có mock PLC stop.
- [ ] Có history.
- [ ] Demo scenario deterministic.
- [ ] Có Start / Stop / Reset.
- [ ] Có thể loop demo liên tục.

---

# 38. Thứ tự implement khuyến nghị

Đừng bắt đầu từ model AI.

Làm đúng thứ tự:

```text
1. good artwork
      ↓
2. synthetic master roll
      ↓
3. mock source
      ↓
4. live frame endpoint
      ↓
5. React live view
      ↓
6. annotations
      ↓
7. mock detector
      ↓
8. defect WebSocket
      ↓
9. telemetry
      ↓
10. history
      ↓
11. alarm
      ↓
12. real detector
```

Nếu bước 1–11 chạy tốt thì đã có một demo end-to-end hoàn chỉnh.

---

# 39. Recommended first milestone

Milestone đầu tiên nên rất nhỏ:

```text
master_roll.jpg
       ↓
MockImageSource
       ↓
FastAPI
       ↓
/api/live/frame.jpg
       ↓
React
       ↓
5-lane moving image
```

Chỉ khi milestone này chạy ổn mới thêm defect detection.

---

# 40. Tài liệu tham khảo

## Taktpixel2025PD-CD

https://github.com/taktpixel/Taktpixel2025PD-CD

Dataset dành cho printed-material inspection, có master image, defective image và pixel-level mask; gồm các nhóm black spot, color shift, friction, hair, line và pinhole.

## Basler Line Scan Documentation

https://docs.baslerweb.com/line-scan-gige-use-cases

Tham khảo cách line-scan camera xử lý endless material và dùng shaft encoder để đồng bộ line trigger với chuyển động vật liệu.

## FastAPI WebSocket

https://fastapi.tiangolo.com/advanced/websockets/

Dùng cho telemetry và defect event realtime giữa inspection app và frontend.

---

# Kết luận

MVP nên được xem như một **digital simulator của dây chuyền inspection**, không phải simulator camera vật lý.

Core abstraction:

```text
ImageSource
    ↓
Detector
    ↓
Inspection Service
    ↓
Roll / Alarm State
    ↓
REST + WebSocket
    ↓
Frontend
```

Demo:

```text
MockSource + MockDetector
```

Production:

```text
LineScanSource + RealDetector
```

Như vậy phần lớn code xây cho demo vẫn có thể tái sử dụng khi tích hợp camera và AI thật.
