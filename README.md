# Printing Inspection Demo

A deterministic five-lane web-inspection system. It generates separate clean-reference and inspected rolls, moves the inspected image according to a 200–300 m/min machine profile, detects defects from pixels with OpenCV, stores traceability data, and presents the result in an industrial HMI.

## Run with Docker

Requirements: Docker Engine and Docker Compose.

```bash
docker compose up --build
```

Open <http://localhost:3000>. The backend API is also exposed at <http://localhost:8000> for diagnostics.

The first startup generates a clean 1920×30000 reference, a separate inspected roll containing defects, and a ground-truth JSON file. Generated images, thumbnails, and SQLite history are kept in the `inspection-data` Docker volume. Later starts reuse the generated rolls while their configuration signature is unchanged. Ground truth is used for evaluation only; the default runtime detector never reads it.

```bash
# Stop services without deleting history
docker compose down

# Explicitly remove the demo volume and all generated/history data
docker compose down --volumes
```

## Demo flow

1. Press **START**. The roll accelerates through the deterministic speed profile.
2. Defects enter the camera viewport and are detected from pixel differences against the clean reference.
3. A long color-shift region demonstrates bad-ratio warning.
4. Five dark spots between 520–528 m demonstrate consecutive-defect warning.
5. The streak at 600 m warns after 1 m and triggers `PLC_STOP` after 3 m.
6. Press **RESET** to archive the stopped roll and create a new one, then press **START**.

Reset is intentionally rejected while the machine is running. Stop the machine first for an operator reset. A latched PLC stop must be reset before Start is accepted.

## Native development

Backend (Python 3.12):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/create_synthetic_roll.py
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend (Node 22):

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api`, `/health`, and `/ws` to the backend at port 8000.

## Verification

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest -q
PYTHONPATH=. python scripts/evaluate_detector.py

cd ../frontend
npm run build
```

Health and main API checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/status
curl -X POST http://localhost:8000/api/demo/start
curl -X POST http://localhost:8000/api/demo/stop
curl -X POST http://localhost:8000/api/demo/reset
```

## Runtime model

- One background inspection engine owns motion, source, detection, tracking, roll and alarm state.
- The default `reference_diff` detector performs translation registration, reference differencing, morphology, component classification and cross-frame deduplication.
- Set `detector.mode: mock` in `backend/config.yaml` only to compare against the legacy annotation-backed detector.
- `position_m` is the source of truth; image offset is calculated at 40 px/m.
- The 600 px viewport represents the latest 15 m of inspected material.
- Live JPEG is refreshed at 8 FPS and telemetry is broadcast at 10 Hz.
- SQLite uses WAL mode. Rolls, defects, alarms, and thumbnails persist across restarts.
- Backend timestamps are UTC; the browser formats timestamps in its local timezone.

The image-processing path is real, while its input is synthetic. Replacing `MockImageSource` with a camera adapter preserves the detector/API/HMI pipeline. Camera acquisition, encoder synchronization and PLC I/O remain integration boundaries owned by the hardware side.
