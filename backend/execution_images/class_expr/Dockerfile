# Sprint 16 Phase 7B.26 -- the real, approved execution image for
# EVALUATE_EXPRESSION / ResourceClass.CLASS_EXPR ONLY. Deliberately
# separate from backend/Dockerfile (this image never runs the
# application, only the dispatcher, under the guard's fixed security
# posture: network=none, read-only rootfs, cap-drop ALL, non-root
# 10001:10001, no-new-privileges).
#
# Base pinned by digest (recorded via `docker inspect`, not guessed):
#   python@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d
# (tag python:3.12.7-slim-bookworm at the time this was built)
FROM python@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d

# CLASS_EXPR is SymPy-only (execution_launcher/docker_policy.py's own
# _expected_environment() sets no env vars for this class -- confirmed
# by reading that function -- because it never imports NumPy/pandas).
# Installing NumPy/pandas here would contradict that evidence, so only
# sympy is installed, pinned.
RUN pip install --no-cache-dir --no-compile sympy==1.13.3 \
    && rm -rf /root/.cache /var/cache/apt/*

# PYTHONDONTWRITEBYTECODE: the guard runs this container with
# read_only=True rootfs (fixed, not configurable per-image) -- baked
# into the image's own ENV rather than the approved spec's environment
# field (which docker_policy.py fixes to {} for this class and this
# Dockerfile does not, and must not, try to change).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 dispatcher \
    && useradd --uid 10001 --gid dispatcher --no-create-home --shell /usr/sbin/nologin dispatcher

WORKDIR /app
COPY dispatcher/ /app/dispatcher/

USER 10001:10001

ENTRYPOINT []
CMD ["python3", "-m", "dispatcher", "--operation", "evaluate_expression"]
