# Photo upscaler: Real-ESRGAN (x4plus photo model) + GFPGAN face restoration, with a web UI.
# Uses an NVIDIA GPU (CUDA) when one is passed in, otherwise every CPU core.
FROM pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime

# The base's Python is Ubuntu's own and this container's only one, so pip installs into it
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# The base image's own packages get their security updates too
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        git libgl1 libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/*

# Real-ESRGAN at one fixed commit, so every build gets the same code
WORKDIR /app
RUN git init -q . && git remote add origin https://github.com/xinntao/Real-ESRGAN.git \
    && git fetch -q --depth 1 origin a4abfb2979a7bbff3f69f58f58ae324608821e27 && git checkout -q FETCH_HEAD

# numpy<2 and opencv<4.12 keep basicsr/gfpgan working
RUN pip install --no-build-isolation numpy==1.26.4 opencv-python==4.11.0.86 \
        basicsr==1.4.2 facexlib==0.3.0 gfpgan==1.3.8 \
    && pip install --no-build-isolation --no-deps -e .

# basicsr 1.4.2 imports a torchvision module removed in torchvision 0.17+
RUN F=$(python -c "import importlib.util,os; print(os.path.join(os.path.dirname(importlib.util.find_spec('basicsr').origin),'data','degradations.py'))") \
    && sed -i 's/torchvision.transforms.functional_tensor/torchvision.transforms.functional/' "$F"

# Warm-up run: downloads all weights (Real-ESRGAN, GFPGAN, face detector/parser)
# into the image so the container never needs internet at runtime.
RUN python -c "import numpy as np, cv2; cv2.imwrite('/tmp/w.png', np.full((64,64,3),128,np.uint8))" \
    && python inference_realesrgan.py -n RealESRGAN_x4plus -i /tmp/w.png -o /tmp/wo --face_enhance --fp32 \
    && rm -rf /tmp/w.png /tmp/wo

RUN pip install fastapi==0.141.1 starlette==1.7.0 uvicorn==0.54.0 python-multipart==0.0.32 spandrel==0.4.2

# Extra upscaling models listed in config.MODELS (the picker in the UI)
COPY web/config.py /srv/web/config.py
RUN cd /srv/web && python -c "import config; from basicsr.utils.download_util import load_file_from_url; \
    [load_file_from_url(url, model_dir=str(config.WEIGHTS_DIR)) for model in config.MODELS.values() for url in model['urls']]"

# HEIC/HEIF photos from phones; the wheel bundles libheif. After the weights, so changing it doesn't download them again.
# The last install: pip then goes, since it carries old copies of msgpack and setuptools and the app never needs it
RUN pip install pillow==12.3.0 pillow-heif==1.8.0 && pip uninstall -y pip

# Batch mode (no UI): docker compose run --rm --entrypoint run.sh upscaler
COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

COPY web /srv/web
# Runs as any --user; HOME must be writable for torch/matplotlib caches
ENV HOME=/tmp PORT=47291 DATA_DIR=/data
EXPOSE 47291
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
ARG VERSION=dev
# The source label links the package on GitHub's registry to the repository
LABEL org.opencontainers.image.title="Upscale" \
      org.opencontainers.image.description="Photo upscaler with a web UI: Real-ESRGAN and GFPGAN on an NVIDIA GPU" \
      org.opencontainers.image.source="https://github.com/aiulian25/upscale" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
CMD ["python", "/srv/web/server.py"]
