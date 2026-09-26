# Printing Inspection Demo

A deterministic five-lane web-inspection system. Its default demo roll uses a real food-packaging photograph from Open Food Facts and transfers real defect residuals from Taktpixel2025PD-CD master/target pairs. It is augmented with camera-style noise and transported at a fixed logical speed of 300 m/min. OpenCV detects defects from pixels, stores traceability data, and presents the result in an industrial HMI.

## Run with Docker

Requirements: Docker Engine and Docker Compose.

```bash
docker compose up --build
```

Open <http://localhost:3000>. The backend API is also exposed at <http://localhost:8000> for diagnostics.

The repository includes a prepared clean 1920×30000 packaging reference and inspected roll. SQLite history and generated thumbnails are kept in the `inspection-data` Docker volume. Ground truth is used for evaluation only; the default runtime detector never reads it.

```bash
# Stop services without deleting history
docker compose down

# Explicitly remove the demo volume and all generated/history data
docker compose down --volumes
```

## Demo flow

1. Press **START**. The roll immediately runs at the fixed demo speed of 300 m/min.
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

# Against a running backend; defaults to a 60-second wall-clock test.
python scripts/benchmark_300m_min.py

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
- The default clock is fixed at 300 m/min (5 m/s), so the 15 m viewport passes the inspection line in exactly 3 seconds.
- The 600 px rolling viewport represents the latest 15 m for HMI history. OpenCV inspects only the newest 4 m (`1920×160`) each cycle instead of reprocessing the overlapping 15 m window.
- Live video is downscaled independently to `960×300`, JPEG quality 68 at 12 FPS; detector coordinates remain at the original `1920 px` width.
- JPEG encoding pauses while the machine is IDLE or STOPPED. Telemetry remains available at 10 Hz.
- SQLite uses WAL mode. Rolls, defects, alarms, and thumbnails persist across restarts.
- Backend timestamps are UTC; the browser formats timestamps in its local timezone.

The image-processing path is real, while the continuous roll and its motion are assembled/simulated from real dataset image pairs. Replacing `MockImageSource` with a camera adapter preserves the detector/API/HMI pipeline. Camera acquisition, encoder synchronization and PLC I/O remain integration boundaries owned by the hardware side.

## Rebuild the Taktpixel roll

The upstream archive is about 640 MB and is not committed. To reproduce or change the prepared subset:

```bash
cd backend
python scripts/download_packaging_artwork.py
python scripts/download_taktpixel.py \
  --output /tmp/Taktpixel2025PD-CD.zip
python scripts/prepare_taktpixel.py \
  --archive /tmp/Taktpixel2025PD-CD.zip \
  --output assets/taktpixel_roll
```

The preparation step repeats the packaging artwork into five lanes, transfers the masked `B - A` residual from paired Taktpixel samples, applies deterministic Gaussian noise, scan-line banding and vertical motion blur, and writes a manifest identifying every source sample. `OUT` is never consumed at runtime.

The packaging photograph is from Open Food Facts and licensed CC BY-SA 3.0. Taktpixel2025PD-CD is by Teppei Tamaki / Taktpixel Co., Ltd., DOI `10.5281/zenodo.15318946`, and licensed CC BY-SA 4.0. See [backend/assets/ATTRIBUTION.md](backend/assets/ATTRIBUTION.md) and the included license text.
