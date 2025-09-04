#!/bin/bash

BENCHMARK=${1:-"llama2-70b"}
NUM_RUNS=${2:-1}
GPU_NAME=${GPU_NAME:-'mi300x'}
RESULT_DIR=${RESULT_DIR:-"results"}

# Change to code directory
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
cd "$SCRIPT_DIR/.."

echo "Starting performance tests on all GPUs..."

for j in $(seq 1 $NUM_RUNS); do
    for i in {0..7}; do
        echo "Starting test on GPU ${i}..."
        ROCR_VISIBLE_DEVICES="${i}" bash run_harness.sh \
            --config-path harness_llm/models/${BENCHMARK}/ \
            --config-name offline_${GPU_NAME} \
            --backend vllm test_mode=performance \
            harness_config.output_log_dir=${RESULT_DIR}/${BENCHMARK}_offline_performance_run_${j}_gpu_${i} \
            harness_config.duration_sec=1 \
            harness_config.total_sample_count=3000 \
            harness_config.device_count=1  &
    done

    echo "All GPU tests started. Waiting for completion..."
    wait

    echo "All GPU performance tests completed successfully for run ${j}."
done
echo "Performance tests on all GPUs completed for ${NUM_RUNS} runs."
echo "Results are stored in the $RESULT_DIR/ directory."

python3 scripts/calculate_buckets.py \
    $RESULT_DIR \
    $RESULT_DIR/results.csv \
    $RESULT_DIR/buckets.csv