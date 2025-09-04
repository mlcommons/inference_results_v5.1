#!/bin/bash

QUANT_OUTPUT_DIR=${QUANT_OUTPUT_DIR:-"/model"}
mkdir -p ${QUANT_OUTPUT_DIR}
LOG_FILE=${LOG_FILE:-"${QUANT_OUTPUT_DIR}/quantization.log"}
MODEL_PATH=${MODEL_PATH:-/model/Llama-3.1-8B-Instruct}
CALIBRATION_DATASET_PATH=${CALIBRATION_DATASET_PATH:-"/data/cnn_dailymail_calibration.json"}

NUM_SAMPLES=${NUM_SAMPLES:-512} # Default to 512 samples for calibration
NUM_GROUPS=${NUM_GROUPS:-128} # Default to 128 groups
NUM_ITERS=${NUM_ITERS:-128} # Default to 128 iterations
NUM_BITS=${NUM_BITS:-4} # Default to 4 bits

node0_cores=$(lscpu | grep "NUMA node0 CPU(s):" | awk '{print $4}')
taskset -c $node0_cores \
python3 run_quantization.py --model_name ${MODEL_PATH} \
    --dataset-path ${CALIBRATION_DATASET_PATH} \
    --nsamples ${NUM_SAMPLES} \
    --iters ${NUM_ITERS} \
    --output_dir ${QUANT_OUTPUT_DIR} \
    --bits ${NUM_BITS} \
    --group_size ${NUM_GROUPS} \
    2>&1 | tee -a ${LOG_FILE}
