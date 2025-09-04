# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	 http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataset import Dataset

import numpy as np
import json
import nltk
import evaluate
import argparse
import nltk
from transformers import AutoTokenizer


def get_args():
    """Parse commandline."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mlperf-accuracy-file", required=True, help="path to mlperf_log_accuracy.json"
    )
    parser.add_argument(
        "--dataset-file",
        required=True,
        help="path to cnn_eval.json")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="verbose messages")
    parser.add_argument(
        "--dtype",
        default="int64",
        help="dtype of the accuracy log",
        choices=["int32", "int64"],
    )
    parser.add_argument(
        "--model-name",
        default="meta-llama/Meta-Llama-3.1-8B-Instruct",
        help="Model name")
    parser.add_argument(
        "--total-sample-count",
        default=13368,
        type=int,
        help="Model name")
    args = parser.parse_args()
    return args


def postprocess_text(preds, targets):
    preds = [pred.strip() for pred in preds]
    targets = [target.strip() for target in targets]

    # rougeLSum expects newline after each sentence
    preds = ["\n".join(nltk.sent_tokenize(pred)) for pred in preds]
    targets = ["\n".join(nltk.sent_tokenize(target)) for target in targets]

    return preds, targets


def main():

    args = get_args()
    model_name = args.model_name
    dataset_path = args.dataset_file
    total_sample_count = args.total_sample_count
    metric = evaluate.load("rouge")
    nltk.download("punkt")
    nltk.download('punkt_tab')

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        model_max_length=2048,
        padding_side="left",
        use_fast=False,
    )
    tokenizer.pad_token = tokenizer.eos_token
    data_object = Dataset(
        model_name=args.model_name,
        dataset_path=dataset_path,
        total_sample_count=total_sample_count,
    )

    targets = data_object.targets

    with open(args.mlperf_accuracy_file, "r") as f:
        results = json.load(f)

    # Deduplicate the results loaded from the json
    dedup_results = []
    seen = set()
    for result in results:
        item = result["qsl_idx"]
        if item not in seen:
            seen.add(item)
            dedup_results.append(result)
    results = dedup_results

    target_required = []
    preds_token_ids = []

    eval_dtype = np.int64
    if args.dtype == "int32":
        eval_dtype = np.int32

    for pred in results:
        qsl_idx = pred["qsl_idx"]
        target = targets[qsl_idx]
        target_required.append(target)
        preds_token_ids.append(
            np.frombuffer(
                bytes.fromhex(
                    pred["data"]),
                eval_dtype))

    preds_decoded_text = tokenizer.batch_decode(
        preds_token_ids, skip_special_tokens=True
    )

    preds, targets = postprocess_text(preds_decoded_text, target_required)

    result = metric.compute(
        predictions=preds, references=targets, use_stemmer=True, use_aggregator=False
    )
    result = {k: f"{round(np.mean(v) * 100, 4)}" for k, v in result.items()}
    prediction_lens = [len(pred) for pred in preds]
    result["gen_len"] = np.sum(prediction_lens)
    result["gen_num"] = len(preds)
    print("\nResults\n")
    print(result)


if __name__ == "__main__":
    main()
