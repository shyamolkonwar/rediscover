# Build on the research VM only. Runtime networking is disabled by sandbox.py.
FROM python:3.12-slim
RUN python -m pip install --no-cache-dir --upgrade pip==26.3 \
    && python -m pip install --no-cache-dir \
    numpy==2.2.6 scipy==1.15.3 astropy==7.1.0 \
    && mkdir -p /input /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /work
USER 65534:65534
ENTRYPOINT ["python", "-I", "-B", "-u", "/work/experiment.py"]
