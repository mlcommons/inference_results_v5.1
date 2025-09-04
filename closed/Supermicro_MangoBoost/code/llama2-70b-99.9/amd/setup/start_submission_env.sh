#!/bin/bash
set -xeu

# Timestamp
export LAB_TS=`date +%m%d-%H%M`

# Host side
export LAB_MLPINF=$(dirname $(dirname $(readlink -fm -- $0)))
export LAB_MLPINF_CODE=${LAB_MLPINF}/code
export LAB_MLPINF_SUBMISSION=${LAB_MLPINF}/submission
export LAB_MLPINF_SETUP=${LAB_MLPINF}/setup
export LAB_MLPINF_TOOLS=${LAB_MLPINF}/tools

export LAB_MODEL="${LAB_MODEL:-/data/inference/model/}"
export LAB_DATASET="${LAB_DATASET:-/data/inference/data/}"

# Docker
export LAB_DKR_CTNAME_BASE=mlperf.vllm.$(whoami)
export LAB_DKR_CTNAME=${LAB_DKR_CTNAME_BASE}.${LAB_TS}

docker run --rm -it --ipc=host --network=host --privileged --cap-add=CAP_SYS_ADMIN --device=/dev/kfd --device=/dev/dri --device=/dev/mem \
        --group-add render --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
        --name=${LAB_DKR_CTNAME} \
        -v ${LAB_MODEL}:/model/ \
        -v ${LAB_DATASET}:/data/ \
        -v ${LAB_MLPINF_CODE}:/lab-mlperf-inference/code \
        -v ${LAB_MLPINF_SUBMISSION}:/lab-mlperf-inference/submission \
        -v ${LAB_MLPINF_SETUP}:/lab-mlperf-inference/setup \
        -v ${LAB_MLPINF_TOOLS}:/lab-mlperf-inference/tools \
        mlperf_inference_submission:5.0
