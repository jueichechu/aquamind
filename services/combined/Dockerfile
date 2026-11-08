FROM node:24.21.0-bookworm-slim AS web-build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --prod=false
COPY apps/web apps/web
COPY evals/fixtures evals/fixtures
ENV NEXT_TELEMETRY_DISABLED=1 AQUAMIND_STATIC_EXPORT=1
# Only this build-stage copy omits Next's server-only routes. Local development
# keeps those routes; the deployed public adapter implements them in Python.
RUN find apps/web -type f \( -name '*.test.ts' -o -name '*.test.tsx' \) -delete \
 && rm -r apps/web/src/app/api && pnpm build --webpack

FROM python:3.14.2-slim AS python-build
WORKDIR /app
COPY ml/requirements*.txt ml/
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu -r ml/requirements.txt \
 && python -m pip install --no-cache-dir -r ml/requirements-cloud.txt \
 && python -m pip check
COPY ml/aquamind_ml/model_release.py ml/aquamind_ml/model.py ml/aquamind_ml/calibration.py ml/aquamind_ml/detector.py ml/aquamind_ml/
COPY ml/model-release-v1.json ml/model-release-v1.json
RUN PYTHONPATH=ml python -m aquamind_ml.model_release --output ml/artifacts/served-detector-v1
COPY ml/aquamind_ml ml/aquamind_ml

FROM python-build AS runtime
COPY --from=web-build /app/apps/web/out apps/web/out
COPY ml/data/demo ml/data/demo
COPY apps/web/src/lib/water/scenario-weather.json apps/web/src/lib/water/scenario-weather.json
RUN useradd --system --uid 10001 --create-home aquamind
USER aquamind
ENV PYTHONPATH=ml PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    AQUAMIND_DETECTOR_PATH=ml/artifacts/served-detector-v1
CMD ["sh", "-c", "exec python -m uvicorn aquamind_ml.web:app --host 0.0.0.0 --port \"${PORT:-10000}\" --workers 1 --no-proxy-headers --no-access-log"]
