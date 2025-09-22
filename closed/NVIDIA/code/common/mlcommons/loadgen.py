# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# Standard library imports
import dataclasses as dcls
import json
import logging
import os
import shutil
import sys
import textwrap
from collections import namedtuple
from csv import DictWriter
from pathlib import Path
from typing import ClassVar, Optional

# Third-party imports
# pylint: disable=c-extension-no-member
import mlperf_loadgen as lg  # type: ignore[attr-defined]
import packaging.version as versioning
from nvmitten.configurator import bind, autoconfigure
from nvmitten.importer import import_from

# Local imports
from .. import paths
from .. import constants as C
from ...fields import harness as harness_fields
from ...fields import loadgen as lg_fields
from ...fields import models as model_fields

if os.environ.get('MLC_MLPERF_INFERENCE_SOURCE', '') != '':
    submission_checker = import_from([Path(os.environ['MLC_MLPERF_INFERENCE_SOURCE']) / "tools" / "submission"] + sys.path, "submission_checker")
else:
    submission_checker = import_from([paths.MLCOMMONS_INF_REPO / "tools" / "submission"] + sys.path, "submission_checker")
    
_latest_ver = max(versioning.parse(ver_key) for ver_key in submission_checker.MODEL_CONFIG.keys())
_vstr = f"v{_latest_ver}"
if _vstr != C.VERSION:
    logging.warning("Current submission version is %s but latest version in submission checker is %s", C.VERSION, _vstr)

model_config = submission_checker.MODEL_CONFIG[_vstr]
benchmark_qsl_size_map = model_config["performance-sample-count"].copy()

if "resnet" in benchmark_qsl_size_map:
    # ResNet is deprecated from v5.1 onwards. Leave here for now.
    # Set to 2048 since the value in MLCommons repo is 1024, which would cause BS2048 to not be contiguous, which is a
    # commonly used batch size in our configurations.
    benchmark_qsl_size_map["resnet"] = 2048
    # submission-checker uses 'resnet' instead of 'resnet50'
    benchmark_qsl_size_map["resnet50"] = benchmark_qsl_size_map["resnet"]

# TODO: Remove when we add it in loadgen
benchmark_qsl_size_map["mixtral-8x7b"] = benchmark_qsl_size_map["mixtral-8x7b-99"] = 15000

# NOTE(vir): primary name/key is 3_1 not 3.1
benchmark_qsl_size_map['llama3_1-405b'] = benchmark_qsl_size_map['llama3.1-405b']


# Check for query constraints documented in https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc#scenarios
_min_queries = model_config["min-queries"].copy()

# Offline uses min. samples/query since min query count is always 1. For other scenarios, these values are the same
# across benchmarks.
QueryConstraint = namedtuple("QueryConstraint", ["name", "val"])
QUERY_METRIC_CONSTRAINTS = {
    C.Scenario.Offline: QueryConstraint("effective_samples_per_query", submission_checker.OFFLINE_MIN_SPQ),
    C.Scenario.Server: QueryConstraint("effective_min_query_count", _min_queries["resnet"]["Server"]),
    # No min query count for Interactive.
    C.Scenario.Interactive: QueryConstraint("effective_min_query_count", _min_queries["resnet"]["Server"]),
    C.Scenario.MultiStream: QueryConstraint("effective_min_query_count", _min_queries["resnet"]["MultiStream"]),
    C.Scenario.SingleStream: QueryConstraint("effective_min_query_count", _min_queries["resnet"]["SingleStream"]),
}


def _scale(x: Optional[float], fac: float):
    """Scale a value by a factor if it's not None.

    Args:
        x: The value to scale, or None
        fac: The scaling factor

    Returns:
        The scaled value, or None if x was None
    """
    if x is None:
        return None
    return x * fac


@autoconfigure
@bind(lg_fields.performance_sample_count)
@bind(lg_fields.performance_sample_count_override)
@bind(lg_fields.min_query_count)
@bind(lg_fields.max_query_count)
@bind(lg_fields.min_duration)
@bind(lg_fields.max_duration)
@bind(harness_fields.test_run)
@dcls.dataclass
class UserConf:
    """Base class for user.conf representation. Subclasses must be dataclasses, where the dataclass field name must be
    the same as that key in Loadgen's user.conf.

    Attributes:
        qsl_size_default: Default size for the query sample library
        performance_sample_count: Number of samples to use for performance testing
        performance_sample_count_override: Override for performance sample count
        min_query_count: Minimum number of queries to run
        max_query_count: Maximum number of queries to run
        min_duration: Minimum duration in milliseconds
        max_duration: Maximum duration in milliseconds
        test_run: Whether this is a test run
    """
    scenario: ClassVar[C.Scenario] = None  # type: ignore[assignment]

    qsl_size_default: int
    performance_sample_count: Optional[int] = None
    performance_sample_count_override: Optional[int] = None
    min_query_count: Optional[int] = None
    max_query_count: Optional[int] = None
    min_duration: Optional[int] = None
    max_duration: Optional[int] = None
    test_run: bool = False

    def __post_init__(self):
        """Initialize derived fields after dataclass initialization.

        Sets up test run duration and performance sample count based on configuration.
        """
        if self.test_run:
            self.min_duration = 60 * 1000  # 1min

        if self.performance_sample_count is None:
            if self.performance_sample_count_override is not None:
                self.performance_sample_count = self.performance_sample_count_override
            else:
                self.performance_sample_count = self.qsl_size_default

        if self.performance_sample_count_override is None:
            self.performance_sample_count_override = self.performance_sample_count

    def export(self, path: Path):
        """Export configuration to a file.

        Args:
            path: Path to write the configuration to
        """
        if not hasattr(self.__class__, "scenario") or self.__class__.scenario is None:
            raise ValueError("Cannot export configuration for base class UserConf")

        with path.open(mode='w') as f:
            for field in dcls.fields(self):
                if not field.init or field.default == dcls.MISSING:
                    continue

                # Do not write special bookkeeping fields
                if field.name in {"test_run"}:
                    continue

                val = getattr(self, field.name)
                if val is not None:
                    f.write(f"*.{self.__class__.scenario.valstr}.{field.name} = {val}\n")  # type: ignore[no-member]


@autoconfigure
@bind(lg_fields.single_stream_expected_latency_ns, "target_latency")
@bind(lg_fields.single_stream_target_latency_percentile, "target_latency_percentile")
@dcls.dataclass
class SingleStreamSettings(UserConf):
    """Settings for SingleStream scenario.

    Attributes:
        target_latency: Target latency in nanoseconds
        target_latency_percentile: Target latency percentile
    """
    scenario: ClassVar[C.Scenario] = C.Scenario.SingleStream

    target_latency: Optional[int] = None
    target_latency_percentile: Optional[float] = None

    def __post_init__(self):
        super().__post_init__()

        # Flag is in ns, but loadgen expects ms
        self.target_latency = _scale(self.target_latency, 1e-6)


@autoconfigure
@bind(lg_fields.multi_stream_expected_latency_ns, "target_latency")
@bind(lg_fields.multi_stream_target_latency_percentile, "target_latency_percentile")
@bind(lg_fields.multi_stream_samples_per_query, "samples_per_query")
@dcls.dataclass
class MultiStreamSettings(UserConf):
    """Settings for MultiStream scenario.

    Attributes:
        target_latency: Target latency in nanoseconds
        target_latency_percentile: Target latency percentile
        samples_per_query: Number of samples per query
    """
    scenario: ClassVar[C.Scenario] = C.Scenario.MultiStream

    target_latency: Optional[int] = None
    target_latency_percentile: Optional[float] = None
    samples_per_query: Optional[int] = None

    def __post_init__(self):
        super().__post_init__()

        # Flag is in ns, but loadgen expects ms
        self.target_latency = _scale(self.target_latency, 1e-6)


@autoconfigure
@bind(lg_fields.offline_expected_qps, "target_qps")
@dcls.dataclass
class OfflineSettings(UserConf):
    """Settings for Offline scenario.

    Attributes:
        target_qps: Target queries per second
    """
    scenario: ClassVar[C.Scenario] = C.Scenario.Offline

    target_qps: Optional[int] = None

    def __post_init__(self):
        super().__post_init__()
        if self.test_run:
            self.min_query_count = 1


@autoconfigure
@bind(lg_fields.server_target_qps, "target_qps")
@bind(lg_fields.server_target_latency_percentile, "target_latency_percentile")
@bind(lg_fields.server_target_latency_ns, "target_latency")
@bind(lg_fields.server_target_qps_adj_factor, "target_qps_adj_factor")
@dcls.dataclass
class ServerSettings(UserConf):
    """Settings for Server scenario.

    Attributes:
        target_qps: Target queries per second
        target_latency_percentile: Target latency percentile
        target_latency: Target latency in nanoseconds
        target_qps_adj_factor: Adjustment factor for target QPS
    """
    scenario: ClassVar[C.Scenario] = C.Scenario.Server

    target_qps: Optional[int] = None
    target_latency_percentile: Optional[float] = None
    target_latency: Optional[int] = None
    target_qps_adj_factor: float = 1.0

    def __post_init__(self):
        super().__post_init__()

        if self.test_run:
            self.min_query_count = 1

        # Flag is in ns, but loadgen expects ms
        self.target_latency = _scale(self.target_latency, 1e-6)

        if self.target_qps_adj_factor is not None:
            self.target_qps = _scale(self.target_qps, self.target_qps_adj_factor)
            self.target_qps_adj_factor = None


@autoconfigure
@bind(lg_fields.server_target_qps, "target_qps")
@bind(lg_fields.server_target_latency_percentile, "target_latency_percentile")
@bind(lg_fields.server_target_latency_ns, "target_latency")
@bind(lg_fields.server_target_qps_adj_factor, "target_qps_adj_factor")
@dcls.dataclass
class InteractiveSettings(UserConf):
    """Settings for Interactive scenario.

    Attributes:
        target_qps: Target queries per second
        target_latency_percentile: Target latency percentile
        target_latency: Target latency in nanoseconds
        target_qps_adj_factor: Adjustment factor for target QPS
    """
    # Temporary fix till loadgen makes Interactive a scenario instead of a Benchmark.
    scenario: ClassVar[C.Scenario] = C.Scenario.Server

    target_qps: Optional[int] = None
    target_latency_percentile: Optional[float] = None
    target_latency: Optional[int] = None
    target_qps_adj_factor: float = 1.0

    def __post_init__(self):
        super().__post_init__()

        if self.test_run:
            self.min_query_count = 1

        # Flag is in ns, but loadgen expects ms
        self.target_latency = _scale(self.target_latency, 1e-6)

        if self.target_qps_adj_factor is not None:
            self.target_qps = _scale(self.target_qps, self.target_qps_adj_factor)
            self.target_qps_adj_factor = None


def scenario_settings(scenario: C.Scenario):
    """Get the appropriate settings class for a given scenario.

    Args:
        scenario: The scenario to get settings for

    Returns:
        The appropriate settings class for the scenario
    """
    return {C.Scenario.SingleStream: SingleStreamSettings,
            C.Scenario.MultiStream: MultiStreamSettings,
            C.Scenario.Offline: OfflineSettings,
            C.Scenario.Server: ServerSettings,
            C.Scenario.Interactive: InteractiveSettings}[scenario]


@autoconfigure
@bind(lg_fields.mlperf_conf_path)
@bind(lg_fields.user_conf_path)
@bind(model_fields.precision)
@bind(model_fields.input_dtype)
@bind(lg_fields.test_mode)
@dcls.dataclass
class LoadgenSettings:
    """Settings for MLPerf loadgen configuration.

    Attributes:
        system_name: Name of the system
        benchmark: Benchmark to run
        scenario: Scenario to run
        workload_setting: Workload settings
        input_dtype: Input data type
        precision: Precision to use
        test_mode: Test mode to run
        mlperf_conf_path: Path to mlperf.conf
        user_conf_path: Path to user.conf
    """

    system_name: str
    benchmark: C.Benchmark
    scenario: C.Scenario
    workload_setting: C.WorkloadSetting = C.WorkloadSetting()
    input_dtype: C.Precision = C.Precision.FP32
    precision: C.Precision = C.Precision.FP32
    test_mode: str = "PerformanceOnly"

    mlperf_conf_path: Optional[os.PathLike] = None
    user_conf_path: Optional[os.PathLike] = None

    full_benchmark_name: str = dcls.field(init=False)
    directory: os.PathLike = dcls.field(init=False)

    def to_lg_obj(self, force_export: bool = False) -> lg.TestSettings:
        """Convert settings to loadgen TestSettings object.

        Args:
            force_export: Whether to force export of configuration files

        Returns:
            Loadgen TestSettings object
        """
        if force_export:
            self.export_mlperf_conf()
            self.export_user_conf()

        ts = lg.TestSettings()
        ts.scenario = self.scenario.to_lg_obj()
        ts.mode = C.test_mode_to_lg_obj(self.test_mode)

        # TODO: Temporary fix till loadgen makes Interactive a scenario instead of a Benchmark.
        benchmark_name = self.benchmark.valstr
        server_name = self.scenario.valstr
        if self.scenario == C.Scenario.Interactive:
            benchmark_name = f"{benchmark_name}-interactive"
            server_name = "Server"

        ts.FromConfig(str(self.mlperf_conf_path),
                      benchmark_name,
                      server_name,
                      2)
        ts.FromConfig(str(self.user_conf_path),
                      benchmark_name,
                      server_name,
                      1)
        return ts

    def __post_init__(self):
        """Initialize derived fields after dataclass initialization.

        Sets up paths and creates necessary directories.
        """
        self.full_benchmark_name = C.submission_benchmark_name(self.benchmark, self.workload_setting.accuracy_target)
        self.directory = paths.BUILD_DIR / "loadgen-configs" / self.system_name / self.full_benchmark_name / self.scenario.valstr
        os.makedirs(self.directory, exist_ok=True)

        if self.mlperf_conf_path is None:
            self.mlperf_conf_path = self.directory / "mlperf.conf"

        if self.user_conf_path is None:
            self.user_conf_path = self.directory / "user.conf"

    def export_mlperf_conf(self):
        """Export mlperf.conf file."""
        shutil.copyfile(paths.MLCOMMONS_INF_REPO / "loadgen" / "mlperf.conf", self.mlperf_conf_path)

    def export_user_conf(self):
        """Export user.conf file.

        Returns:
            UserConf object with the exported configuration
        """
        user_conf = scenario_settings(self.scenario)(benchmark_qsl_size_map[self.full_benchmark_name])
        user_conf.export(self.user_conf_path)
        return user_conf

    def export_readme(self):
        """Export README.md file with instructions for running the benchmark."""
        if "Triton_CPU" in self.system_name:
            readme_str = textwrap.dedent(f"""\
            To run this benchmark, first follow the setup steps in `closed/NVIDIA/README_Triton_CPU.md`. Then to run the harness:

            ```
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --test_mode=AccuracyOnly"
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --test_mode=PerformanceOnly"
            ```

            For more details, please refer to `closed/NVIDIA/README_Triton_CPU.md`.""")
        elif "Triton" in self.system_name:
            readme_str = textwrap.dedent(f"""\
            To run this benchmark, first follow the setup steps in `closed/NVIDIA/README.md`. Then to run the harness:

            ```
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --harness_type=triton --test_mode=AccuracyOnly"
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --harness_type=triton --test_mode=PerformanceOnly"
            ```

            For more details, please refer to `closed/NVIDIA/README.md`.""")
        else:
            readme_str = textwrap.dedent(f"""\
            To run this benchmark, first follow the setup steps in `closed/NVIDIA/README.md`. Then to generate the TensorRT engines and run the harness:

            ```
            make generate_engines RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr}"
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --test_mode=AccuracyOnly"
            make run_harness RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr} --test_mode=PerformanceOnly"
            ```

            For more details, please refer to `closed/NVIDIA/README.md`.""")

        if "HeteroMultiUse" in self.system_name:
            readme_str = textwrap.dedent("""\
            To run this benchmark, first follow the setup steps in `closed/NVIDIA/README.md`. Then to generate the TensorRT
            engines and run the harness, first read the **Using Multiple MIG slices** section in `closed/NVIDIA/README.md`.
            Then follow the instructions in `closed/NVIDIA/documentation/heterogeneous_mig.md` to run benchmarks.""")

        with (self.directory / "README.md").open(mode='w') as f:
            f.write(readme_str)

    def export_calib_adoc(self):
        """Export calibration process documentation."""
        if "Triton_CPU" in self.system_name:
            calibration_process_str = textwrap.dedent(f"""\
            To calibrate this benchmark, please follow the steps in `closed/NVIDIA/calibration_triton_cpu/OpenVINO/{self.benchmark.valstr}/README.md`.""")
        else:
            calibration_process_str = textwrap.dedent(f"""\
            To calibrate this benchmark, first follow the setup steps in `closed/NVIDIA/README.md`.

            ```
            make calibrate RUN_ARGS="--benchmarks={self.benchmark.valstr} --scenarios={self.scenario.valstr}"
            ```

            For more details, please refer to `closed/NVIDIA/README.md`.""")

        with (self.directory / "calibration_process.adoc").open(mode='w') as f:
            f.write(calibration_process_str)

    def export_system_json(self):
        """Export system configuration JSON file."""
        if isinstance(self.precision, C.Precision):
            precision = self.precision.valstr
        elif len(self.precision) == 1:
            precision = list(self.precision.values())[0].valstr
        else:
            precision = {}
            for k, v in self.precision.items():
                if isinstance(k, C.AliasedNameEnum):
                    k = k.valstr
                else:
                    k = str(k)
                precision[k] = v.valstr

        if "Triton_CPU" in self.system_name:
            starting_weights_filename_map = {
                C.Benchmark.ResNet50: "The original weight filename: https://zenodo.org/record/2535873/files/resnet50_v1.pb",
                C.Benchmark.Retinanet: "The original weight filename: https://zenodo.org/record/6605272/files/retinanet_model_10.zip",
                C.Benchmark.BERT: "The original weight filename: bert_large_v1_1_fake_quant.onnx",
            }
            weight_transformations_map = {
                C.Benchmark.ResNet50: "We transform the original fp32 weight to int8 weight using symmetric quantization.",
                C.Benchmark.Retinanet: "We transfer the weight from fp32 datatype in ONNX file to int8 datatype in OpenVino IR file.",
                C.Benchmark.BERT: "We transfer the weight from int8 datatype in ONNX file to int8 datatype in OpenVino IR file.",
            }
            if self.benchmark == C.Benchmark.BERT:
                precision = "int8"
        else:
            starting_weights_filename_map = {
                C.Benchmark.ResNet50: "resnet50_v1.onnx",
                C.Benchmark.Retinanet: "retinanet_model_10.pth",
                C.Benchmark.DLRMv2: "model_weights",
                C.Benchmark.BERT: "bert_large_v1_1_fake_quant.onnx",
                C.Benchmark.GPTJ: "pytorch_model-00001-of-00003.bin, pytorch_model-00002-of-00003.bin, pytorch_model-00003-of-00003.bin",
                C.Benchmark.LLAMA2: "Original Huggingface model weights",
                C.Benchmark.LLAMA3_1_8B: "Original Huggingface model weights",
                C.Benchmark.LLAMA3_1_405B: "Original Huggingface model weights",
                C.Benchmark.Mixtral8x7B: "Original Huggingface model weights",
                C.Benchmark.DeepSeek_R1: "Original Huggingface model weights",
                C.Benchmark.SDXL: "Huggingface model weights hosted by MLCommons",
                C.Benchmark.WHISPER: "Original Huggingface model weights",
                C.Benchmark.RGAT: "RGAT.pt hosted by MLCommons"
            }
            weight_transformations_map = {
                C.Benchmark.ResNet50: "quantization, affine fusion",
                C.Benchmark.Retinanet: "quantization, affine fusion",
                C.Benchmark.DLRMv2: "affine fusion",
                C.Benchmark.BERT: "quantization, affine fusion",
                C.Benchmark.GPTJ: "quantization, affine fusion",
                C.Benchmark.LLAMA2: "quantization, affine fusion",
                C.Benchmark.LLAMA3_1_8B: "quantization, affine fusion",
                C.Benchmark.LLAMA3_1_405B: "quantization, affine fusion",
                C.Benchmark.Mixtral8x7B: "quantization, affine fusion",
                C.Benchmark.DeepSeek_R1: "quantization, affine fusion",
                C.Benchmark.SDXL: "quantization, affine fusion",
                C.Benchmark.RGAT: "none",
                C.Benchmark.WHISPER: "quantization, affine fusion",
                C.Benchmark.RGAT: "none"
            }

        data = {
            "input_data_types": self.input_dtype.valstr if isinstance(self.input_dtype, C.Precision) else self.input_dtype,
            "retraining": "No",
            "starting_weights_filename": starting_weights_filename_map[self.benchmark],
            "weight_data_types": precision,
            "weight_transformations": weight_transformations_map[self.benchmark]
        }

        with (self.directory / f"{self.system_name}_{self.scenario.valstr}.json").open(mode='w') as f:
            json.dump(data, f, indent=4, sort_keys=True)

    def export_powersetting_adoc(self):
        """Export power settings documentation."""
        powersetting_str = textwrap.dedent("""\
        ## An example of an unstructured document for Power management settings to reproduce Perf, Power results

        # Boot/BIOS Firmware Settings

        None

        # Management Firmware Settings

        None

        # Power Management Settings  (command line or other)

        Run the scripts described in our code. See the **How to collect power measurements while running the harness**
        section of the README.md located in closed/NVIDIA.
        """)
        with (self.directory / "power_settings.adoc").open(mode='w') as f:
            f.write(powersetting_str)

    def export_analyzer_table(self):
        """Export power analyzer table CSV file."""
        system_name_to_power_cfg_map = {
            # Systems for v4.1
            "DGX-H100_H100-SXM-80GBx8_TRT_MaxQ": "viking-cr-194",
            "H200-SXM-141GBx8_TRT_MaxQ": "viking-prod-302",
            "Orin_NX_TRT_MaxQ": "a1u2n2g-0277-01-jetson",
            "Orin_TRT_MaxQ": "a1u2n2g-0275-01-jetson",
        }

        # Each power meter has three channels (i.e. can take up to three power measurements in parallel) but each has 2000W
        # power limit. For systems whose peak power consumption is greater than 2000W, we need to connect it to multiple
        # channels and get the power readings by summing up the power readings of each channel.
        # In the Yokogawa config file, '52' means the meter is in single channel mode (<= 2000W peak) and '77' means the
        # meter is in multi channel mode (> 2000W peak)
        meter_type_map = {
            "52": "single channel",
            "77": "multi channel",
        }

        def get_num_channels(channel_str):
            """Get number of channels from channel string.

            Args:
                channel_str: Channel string in format 'start,end'

            Returns:
                Number of channels
            """
            t = channel_str.split(",")
            num_channels = 1
            if len(t) > 1:
                num_channels = int(t[1]) - int(t[0]) + 1
            return num_channels

        if self.system_name not in system_name_to_power_cfg_map:
            logging.info("Cannot get power.cfg file for system '%s'", self.system_name)
            return

        with open(f"power/server-{system_name_to_power_cfg_map[self.system_name]}.cfg", encoding='utf-8') as power_file:
            lines = power_file.readlines()

        power_fields = dict()
        for line in lines:
            line = line.strip()
            if len(line) == 0:
                continue
            if line.startswith('['):
                continue
            if line.startswith("#"):
                continue

            t = line.split(": ")
            power_fields[t[0]] = t[1]

        csv_cols = ["vendor",
                    "model",
                    "firmware",
                    "config",
                    "interface",
                    "wiring/topology",
                    "number of channels",
                    "channels used"]

        row = {
            "vendor": "Yokogawa",
            "model": "WT-333E",
            "firmware": "F1.04",
            "config": meter_type_map[power_fields["deviceType"]],
            "interface": "ethernet",
            "wiring/topology": "V3A3",
            "number of channels": str(get_num_channels(power_fields["channel"])),
            "channels used": power_fields["channel"],
        }

        with (self.directory / "analyzer_table.csv").open(mode='w') as csvfile:
            writer = DictWriter(csvfile, fieldnames=csv_cols)
            writer.writeheader()
            writer.writerow(row)

    def export_all(self):
        """Export all configuration files.

        Returns:
            UserConf object with the exported configuration
        """
        self.export_mlperf_conf()
        user_conf = self.export_user_conf()
        self.export_readme()
        self.export_calib_adoc()
        self.export_system_json()

        if self.workload_setting.power_setting == C.PowerSetting.MaxQ:
            self.export_powersetting_adoc()
            self.export_analyzer_table()

        return user_conf


@dcls.dataclass
class LogOutputSettings:
    """Settings for log output configuration.

    Attributes:
        outdir: Output directory for logs
        prefix: Prefix for log files
        suffix: Suffix for log files
        copy_summary_to_stdout: Whether to copy summary to stdout
    """
    outdir: os.PathLike
    prefix: str = "mlperf_log_"
    suffix: str = ""
    copy_summary_to_stdout: bool = True

    def to_lg_obj(self) -> lg.LogOutputSettings:
        """Convert to loadgen LogOutputSettings object.

        Returns:
            Loadgen LogOutputSettings object
        """
        los = lg.LogOutputSettings()
        los.outdir = str(self.outdir)
        los.prefix = self.prefix
        los.suffix = self.suffix
        los.copy_summary_to_stdout = self.copy_summary_to_stdout
        return los


@autoconfigure
@bind(lg_fields.log_mode)
@bind(lg_fields.log_mode_async_poll_interval_ms)
@dcls.dataclass
class LogSettings:
    """Settings for logging configuration.

    Attributes:
        output_settings: Settings for log output
        log_mode: Mode for logging
        log_mode_async_poll_interval_ms: Polling interval for async logging
    """
    output_settings: LogOutputSettings
    log_mode: str = "AsyncPoll"
    log_mode_async_poll_interval_ms: int = 1000

    def to_lg_obj(self):
        """Convert to loadgen LogSettings object.

        Returns:
            Loadgen LogSettings object
        """
        ls = lg.LogSettings()
        ls.log_output = self.output_settings.to_lg_obj()
        ls.log_mode = C.log_mode_to_lg_obj(self.log_mode)
        ls.log_mode_async_poll_interval_ms = self.log_mode_async_poll_interval_ms
        return ls


@dcls.dataclass
class LoadgenResponse:
    """Base-class for per-benchmark 'SUTResponse' classes. Ensures basic loadgen integration methods.

    Attributes:
        request_id: ID of the request
        is_first_token: Whether this is the first token in a sequence
    """
    request_id: int
    is_first_token: bool = False

    def to_query_sample_response(self):
        """Convert to query sample response.

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError

    def submit_to_loadgen(self):
        if self.is_first_token:
            fn = lg.FirstTokenComplete
        else:
            fn = lg.QuerySamplesComplete

        fn([self.to_query_sample_response()])
