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
import contextlib
import dataclasses as dcls
import importlib
import logging
import os
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
import subprocess

# Third-party imports
import tensorrt as trt
import nvmitten.json_utils as json
import nvmitten.nvidia.smi as NvSMI
from nvmitten.configurator import bind, autoconfigure, HelpInfo
from nvmitten.nvidia.accelerator import DLA, GPU
from nvmitten.pipeline import Operation
from nvmitten.utils import run_command

# pylint: disable=c-extension-no-member
import mlperf_loadgen as lg

# Local imports
from ..common import args_to_string
from ..common.constants import Benchmark, Scenario, AuditTest
from ..common.mlcommons.compliance import get_audit_verifier
from ..common.mlcommons.lg_logs import LoadgenLogReader, result_key
from ..common.mlcommons.loadgen import QUERY_METRIC_CONSTRAINTS, LogOutputSettings, LogSettings
from ..common.mlcommons.runner import ScopedQSL, ScopedSUT
from ..common.systems.system_list import DETECTED_SYSTEM, numa_config_string
from ..common.workload import Workload
from ..fields.wrapped import make_autoconf_dcls
from ..plugin import get_trt_plugin_paths_by_network

from ..fields import general as general_fields
from ..fields import harness as harness_fields
from ..fields import loadgen as lg_fields
from ..fields import meta as metafields
from ..fields import models as model_fields

from .generate_engines import EngineBuilderOp
from .loadgen import LoadgenConfFilesOp


@autoconfigure
@bind(harness_fields.vboost_slider, "value")
class Vboost:
    """Context manager for controlling GPU voltage boost settings.

    This class provides a context manager interface for setting and resetting
    GPU voltage boost settings. It is only supported on Hopper architecture GPUs.

    Attributes:
        value (int): The voltage boost value to set.
        is_supported (bool): Whether voltage boost is supported on the current system.
    """

    def __init__(self, value: int = 0):
        """Initialize the Vboost context manager.

        Args:
            value (int, optional): The voltage boost value to set. Defaults to 0.
        """
        self.value = value
        self.is_supported = any(tag in DETECTED_SYSTEM.extras["tags"] for tag in ("is_hopper", "is_blackwell"))

    def __enter__(self):
        """Set the voltage boost value when entering the context.

        Returns:
            Any: The result of setting the voltage boost, if supported.
        """
        if self.is_supported:
            logging.debug("Setting vboost to %d", self.value)
            try:
                NvSMI.set_vboost(self.value)
            except subprocess.CalledProcessError as e:
                logging.info("WARNING: Failed to set vboost slider. Skipping...")

    def __exit__(self, *args):
        """Reset the voltage boost to 0 when exiting the context."""
        if self.is_supported:
            try:
                NvSMI.set_vboost(0)
            except subprocess.CalledProcessError as e:
                logging.info("WARNING: Failed to reset vboost slider.")


@autoconfigure
@bind(Workload.FIELD)
@bind(general_fields.verbose)
@bind(general_fields.verbose_nvtx)
@bind(harness_fields.use_jemalloc)
@bind(lg_fields.test_mode)
@bind(metafields.enable_power_meter, "enable_power_meter")
class BenchmarkHarnessOp(Operation):
    """Base class for benchmark harness operations.

    This class provides the base functionality for running MLPerf benchmarks,
    including power monitoring, environment setup, and logging.

    Attributes:
        verbose (bool): Whether to enable verbose output.
        verbose_nvtx (bool): Whether to enable NVTX profiling.
        use_jemalloc (bool): Whether to use jemalloc for memory allocation.
        test_mode (str): The test mode to run (e.g., "PerformanceOnly").
        enable_power_meter (bool): Whether to enable power monitoring.
        _env_vars (dict): Environment variables for the benchmark.
    """

    @classmethod
    def immediate_dependencies(cls):
        """Get the immediate dependencies of this operation.

        Returns:
            set: Set of operation classes that this operation depends on.
        """
        return {LoadgenConfFilesOp}

    @classmethod
    def output_keys(cls):
        """Get the output keys produced by this operation.

        Returns:
            list: List of output keys.
        """
        return ["log_dir", "result_metadata"]

    def __init__(self,
                 *args,
                 workload: Optional[Workload] = None,
                 verbose: bool = False,
                 verbose_nvtx: bool = False,
                 use_jemalloc: bool = False,
                 test_mode: str = "PerformanceOnly",
                 enable_power_meter: bool = False,
                 **kwargs):
        """Initialize the benchmark harness operation.

        Args:
            verbose (bool, optional): Whether to enable verbose output. Defaults to False.
            verbose_nvtx (bool, optional): Whether to enable NVTX profiling. Defaults to False.
            use_jemalloc (bool, optional): Whether to use jemalloc. Defaults to False.
            test_mode (str, optional): The test mode to run. Defaults to "PerformanceOnly".
            enable_power_meter (bool, optional): Whether to enable power monitoring. Defaults to False.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)

        if workload is None:
            raise ValueError("Workload is required for BenchmarkHarnessOp")
        self.wl = workload

        self.verbose = verbose
        self.verbose_nvtx = verbose_nvtx
        self.use_jemalloc = use_jemalloc
        self.test_mode = test_mode
        self.enable_power_meter = enable_power_meter

        self._env_vars = os.environ.copy()

    def prepend_ld_preload(self, so_path):
        """Prepend a shared library to LD_PRELOAD.

        Args:
            so_path (str): Path to the shared library to preload.
        """
        if "LD_PRELOAD" in self._env_vars:
            self._env_vars["LD_PRELOAD"] = ":".join([so_path, self._env_vars["LD_PRELOAD"]])
        else:
            self._env_vars["LD_PRELOAD"] = so_path

        logging.debug("Updated LD_PRELOAD: %s", self._env_vars["LD_PRELOAD"])

    @contextlib.contextmanager
    def power_monitor(self):
        """Context manager for power monitoring during benchmark execution.

        Args:
            wl (Workload): The workload being monitored.

        Yields:
            PowerMeasurements: The power monitoring object if enabled, None otherwise.
        """
        pm = None

        if self.enable_power_meter:
            if importlib.util.find_spec("code.internal.power_measurements") is None:
                logging.info("Could not load power monitor: Are you an internal user?")
            else:
                pmon_log_name = '_'.join([self.wl.system.extras["id"],
                                          self.wl.benchmark.valstr,
                                          self.wl.scenario.valstr,
                                          f"{self.wl.setting.accuracy_target.value * 100:.1f}%",
                                          "plugin-enabled",
                                          self.wl.setting.harness_type.valstr])
                pmon_log_path = self.wl.log_dir / "power_measurements" / pmon_log_name
                _mod = importlib.import_module("code.internal.power_measurements")
                pm = _mod.PowerMeasurements(pmon_log_path)

        try:
            if pm is not None:
                pm.start()
            yield pm
        finally:
            if pm is not None:
                pm.stop()

    def load_run_results(self):
        """Load and process the results from the benchmark run.

        Returns:
            dict: Dictionary containing the result metadata and log directory.
        """
        log_reader = LoadgenLogReader(self.wl)
        qmc = QUERY_METRIC_CONSTRAINTS[self.wl.scenario]
        rk = result_key(self.wl.benchmark, self.wl.scenario)
        loadgen_query_keys = ["result_validity",
                              rk,
                              "early_stopping_met",
                              qmc.name,
                              "effective_min_duration_ms"]
        # Append QPS for LLMs in Offline
        if self.wl.benchmark.is_llm and self.wl.scenario == Scenario.Offline:
            loadgen_query_keys.append("result_samples_per_second")
        results = log_reader.get_keys(*loadgen_query_keys)

        qmc_measured = float(results[qmc.name])
        satisfies_query_constraint = (qmc_measured >= qmc.val)
        perf_value, perf_metric = log_reader.result_summary(strict_match=False)
        results.update({"system_name": self.wl.submission_system,
                        "base_log_dir": str(self.wl.base_log_dir.absolute()),
                        "tensorrt_version": trt.__version__,
                        "detected_system": DETECTED_SYSTEM.summary_description(),
                        "workload_setting_code": self.wl.setting.short,
                        "benchmark_short": self.wl.benchmark.valstr,
                        "benchmark_full": self.wl.submission_benchmark,
                        "scenario": self.wl.scenario.valstr,
                        "power_meter_enabled": self.enable_power_meter,
                        "avg_power": log_reader.avg_power(),
                        "test_mode": self.test_mode,
                        "scenario_key": rk,
                        "satisfies_query_constraint": satisfies_query_constraint,
                        "true_result_value": perf_value,
                        "true_result_metric": perf_metric})

        # Extra stats for Server scenario
        if self.wl.scenario == Scenario.Server and self.test_mode == "PerformanceOnly":
            serv_lat = log_reader.get_keys("requested_server_ttft_latency",
                                           "result_first_token_99.00_percentile_latency_ns",
                                           "requested_server_tpot_latency",
                                           "result_time_per_output_token_99.00_percentile_ns",
                                           "requested_server_target_latency_ns",
                                           "result_99.00_percentile_latency_ns")

            if serv_lat["requested_server_ttft_latency"]:
                ttft_99 = float(serv_lat["result_first_token_99.00_percentile_latency_ns"])
                ttft_target = float(serv_lat["requested_server_ttft_latency"])
                tpot_99 = float(serv_lat["result_time_per_output_token_99.00_percentile_ns"])
                tpot_target = float(serv_lat["requested_server_tpot_latency"])

                results["latency_usage_ttft"] = ttft_99 / ttft_target
                results["latency_usage_tpot"] = tpot_99 / tpot_target
            else:
                lat_99 = float(serv_lat["result_99.00_percentile_latency_ns"])
                lat_target = float(serv_lat["requested_server_target_latency_ns"])

                results["latency_usage_raw"] = lat_99 / lat_target
        return {"result_metadata": results,
                "log_dir": self.wl.log_dir}


HelpInfo.add_configurator_dependency(BenchmarkHarnessOp, LoadgenLogReader)


class PyHarnessOp(BenchmarkHarnessOp, ScopedSUT):
    """Harness for executing MLPerf benchmarks with Python code.

    This class extends BenchmarkHarnessOp to support running benchmarks using
    Python code, with support for tensor and pipeline parallelism.
    """

    @classmethod
    def immediate_dependencies(cls):
        """Get the immediate dependencies of this operation.

        Returns:
            set: Set of operation classes that this operation depends on.
        """
        return {LoadgenConfFilesOp}

    @classmethod
    def output_keys(cls):
        """Get the output keys produced by this operation.

        Returns:
            list: List of output keys.
        """
        return ["log_dir", "result_metadata"]

    def __init__(self,
                 qsl_cls: Type[ScopedQSL],
                 *args,
                 total_sample_count: Optional[int] = None,
                 **kwargs):
        """Initialize the PyHarnessOp.

        Args:
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)

        self.qsl_cls = qsl_cls
        self.total_sample_count = total_sample_count

        self._qsl_inst = None

    def issue_queries(self, query_samples: List[lg.QuerySample]):
        """Issue queries to the SUT.

        Args:
            query_samples: List of query samples to issue.
        """
        raise NotImplementedError("issue_queries is not implemented for PyHarnessOp")

    def flush_queries(self):
        """Flush queries from the SUT.
        """
        raise NotImplementedError("flush_queries is not implemented for PyHarnessOp")

    @contextlib.contextmanager
    def wrap_lg_test(self, scratch_space, dependency_outputs):
        """Context wrapped around lg.StartTestWithLogSettings. Users of this class should override this method to
        perform any setup or teardown necessary for the SUT before and after the test.

        self._qsl_inst will be set to the ScopedQSL instance before the context is entered.

        Yields:
            None: No value should be yielded for this context.
        """
        yield None

    def run(self, scratch_space, dependency_outputs):
        """Run the benchmark using Python code.

        Args:
            scratch_space: The scratch space for temporary files.
            dependency_outputs: Outputs from dependency operations.

        Returns:
            dict: Dictionary containing the result metadata and log directory.
        """
        user_conf = dependency_outputs[LoadgenConfFilesOp]["user_conf"]
        if self.total_sample_count is None:
            total_sample_count = user_conf.performance_sample_count
        else:
            total_sample_count = self.total_sample_count

        lg_settings = dependency_outputs[LoadgenConfFilesOp]["lg_settings"]
        test_settings = lg_settings.to_lg_obj()

        log_settings = LogSettings(LogOutputSettings(self.wl.log_dir)).to_lg_obj()
        self._qsl_inst = self.qsl_cls(total_sample_count, user_conf.performance_sample_count)
        with self._qsl_inst as qsl, \
                self as sut, \
                Vboost(), \
                self.power_monitor():

            with self.wrap_lg_test(scratch_space, dependency_outputs):
                lg.StartTestWithLogSettings(sut, qsl, test_settings, log_settings)
        self._qsl_inst = None
        return self.load_run_results()


HelpInfo.add_configurator_dependency(PyHarnessOp, LogSettings)


@autoconfigure
@bind(model_fields.use_fp8)
class ExecutableHarness(BenchmarkHarnessOp):
    """Harness for executing MLPerf benchmarks with executable binaries.

    This class extends BenchmarkHarnessOp to support running benchmarks using
    executable binaries, with support for tensor and pipeline parallelism.

    Attributes:
        executable_fpath (Path): Path to the executable binary.
        tp_size (int): Tensor parallelism size.
        pp_size (int): Pipeline parallelism size.
        use_fp8 (bool): Whether to use FP8 precision.
    """

    @classmethod
    def immediate_dependencies(cls):
        """Get the immediate dependencies of this operation.

        Returns:
            set: Set of operation classes that this operation depends on.
        """
        return {EngineBuilderOp, LoadgenConfFilesOp}

    @classmethod
    def output_keys(cls):
        """Get the output keys produced by this operation.

        Returns:
            list: List of output keys.
        """
        return ["log_dir", "result_metadata"]

    def __init__(self,
                 *args,
                 executable_fpath: os.PathLike,
                 use_fp8: bool = False,
                 **kwargs):  # pylint: disable=too-many-arguments
        """Initialize the executable harness.

        Args:
            *args: Additional positional arguments.
            executable_fpath (os.PathLike): Path to the executable binary.
            tensor_parallelism (int, optional): Tensor parallelism size. Defaults to 1.
            pipeline_parallelism (int, optional): Pipeline parallelism size. Defaults to 1.
            use_fp8 (bool, optional): Whether to use FP8 precision. Defaults to False.
            **kwargs: Additional keyword arguments.
        """
        super().__init__(*args, **kwargs)

        self.executable_fpath = Path(executable_fpath)
        if not self.executable_fpath.exists():
            raise FileNotFoundError(f"No executable found at {self.executable_fpath}")
        elif not os.access(self.executable_fpath, os.X_OK):
            raise PermissionError(f"{self.executable_fpath} does not have executable permissions")

        self.use_fp8 = use_fp8

    def build_flags(self, user_conf, engine_index):
        """Build the command line flags for the benchmark executable.

        Args:
            user_conf: The user configuration.
            engine_index: The engine index configuration.

        Returns:
            dict: Dictionary of command line flags.
        """
        log_dir = engine_index.wl.log_dir
        flag_dict = {"verbose": self.verbose,
                     "verbose_nvtx": self.verbose_nvtx,
                     "logfile_outdir": str(log_dir),
                     "logfile_prefix": "mlperf_log_",
                     "performance_sample_count": user_conf.performance_sample_count,
                     "test_mode": self.test_mode}

        benchmark = engine_index.wl.benchmark
        plugins = get_trt_plugin_paths_by_network(benchmark, use_fp8=self.use_fp8)
        if len(plugins) > 0:
            logging.debug("The harness will load %d plugins: %s", len(plugins), plugins)
            flag_dict["plugins"] = ",".join(str(elem) for elem in plugins)

        # Add engines
        for dev_type in engine_index.wl.device_types:
            flag_dict[f"{dev_type}_batch_size"] = engine_index.bs_info.e2e(dev=dev_type)

        _d = {"gpu": {"engines": [],
                      "batch_sizes": []},
              "dla": {"engines": [],
                      "batch_sizes": []}}
        for c_eng, _ in engine_index.iter_components():
            eng_fpath = engine_index.full_path(c_eng)
            if not eng_fpath.exists():
                raise FileNotFoundError(f"Engine file {eng_fpath} does not exist.")

            _d[c_eng.device_type]["engines"].append(eng_fpath)
            _d[c_eng.device_type]["batch_sizes"].append(str(c_eng.batch_size))

        for dev_type, dev_dict in _d.items():
            if len(dev_dict["engines"]) > 0:
                flag_dict[f"{dev_type}_engine_batch_size"] = ','.join(dev_dict["batch_sizes"])
                flag_dict[f"{dev_type}_engines"] = ','.join(str(p) for p in dev_dict["engines"])

        return flag_dict

    def run(self, scratch_space, dependency_outputs):
        """Run the benchmark executable.

        Args:
            scratch_space: The scratch space for temporary files.
            dependency_outputs: Outputs from dependency operations.

        Returns:
            dict: Dictionary containing the result metadata and log directory.
        """
        user_conf = dependency_outputs[LoadgenConfFilesOp]["user_conf"]
        engine_index = dependency_outputs[EngineBuilderOp]["engine_index"]
        assert self.wl == engine_index.wl, f"Workload mismatch: {self.wl} != {engine_index.wl}"

        # Build flags
        flags = self.build_flags(user_conf, engine_index)
        flags["mlperf_conf_path"] = str(dependency_outputs[LoadgenConfFilesOp]["mlperf_conf_path"])
        flags["user_conf_path"] = str(dependency_outputs[LoadgenConfFilesOp]["user_conf_path"])
        argstr = args_to_string(flags)

        # Prepend jemalloc if enabled
        if self.use_jemalloc:
            self.prepend_ld_preload(f"/usr/lib/{platform.processor()}-linux-gnu/libjemalloc.so.2")

        cmd = f"{self.executable_fpath} {argstr}"

        with Vboost(), self.power_monitor():
            run_command(cmd, custom_env=self._env_vars)

        return self.load_run_results()


def _lwis_flag_remap(self):
    """Remap LWIS flags to their appropriate command line arguments.

    Returns:
        dict: Dictionary of remapped flags.
    """
    d = dcls.asdict(self)
    d["v"] = d.pop("glog_verbosity") if d.get("glog_verbosity", None) else 0

    if d.get("gpu_indices", None):
        d["devices"] = d.pop("gpu_indices")
    else:
        d["devices"] = ','.join(str(gpu.gpu_index) for gpu in DETECTED_SYSTEM.accelerators[GPU])

    # Cleanup
    return {k: v for k, v in d.items() if v is not None}


LWISFlags = make_autoconf_dcls("LWISFlags",
                               harness_fields.gpu_indices,
                               harness_fields.glog_verbosity,
                               harness_fields.map_path,
                               harness_fields.tensor_path,
                               harness_fields.assume_contiguous,
                               harness_fields.coalesced_tensor,
                               harness_fields.gpu_copy_streams,
                               harness_fields.gpu_inference_streams,
                               harness_fields.max_dlas,
                               harness_fields.dla_copy_streams,
                               harness_fields.dla_inference_streams,
                               harness_fields.run_infer_on_copy_streams,
                               harness_fields.warmup_duration,
                               harness_fields.use_direct_host_access,
                               harness_fields.use_deque_limit,
                               harness_fields.deque_timeout_usec,
                               harness_fields.use_spin_wait,
                               harness_fields.complete_threads,
                               harness_fields.use_batcher_thread_per_device,
                               harness_fields.use_cuda_thread_per_device,
                               harness_fields.use_graphs,
                               harness_fields.start_from_device,
                               harness_fields.end_on_device,
                               frozen=True,
                               namespace={"asdict": _lwis_flag_remap})


class LWISExecutableHarness(ExecutableHarness):
    """Harness for executing LWIS (Loadgen Workload Interface System) benchmarks.

    This class extends ExecutableHarness to provide specific functionality for
    LWIS-based benchmarks.
    """

    def __init__(self):
        """Initialize the LWIS executable harness."""
        super().__init__(executable_fpath="./build/bin/harness_default")

        self.conf = LWISFlags()

    @classmethod
    def immediate_dependencies(cls):
        """Get the immediate dependencies of this operation.

        Returns:
            set: Set of operation classes that this operation depends on.
        """
        return {EngineBuilderOp, LoadgenConfFilesOp}

    @classmethod
    def output_keys(cls):
        """Get the output keys produced by this operation.

        Returns:
            list: List of output keys.
        """
        return ["log_dir", "result_metadata"]

    def build_flags(self, user_conf, engine_index):
        """Build the command line flags for the LWIS benchmark executable.

        Args:
            user_conf: The user configuration.
            engine_index: The engine index configuration.

        Returns:
            dict: Dictionary of command line flags.
        """
        flags = super().build_flags(user_conf, engine_index)
        flags.update(self.conf.asdict())

        self.use_jemalloc = (Scenario.Server == engine_index.wl.scenario)
        n_dlas = len(DETECTED_SYSTEM.accelerators[DLA])
        if "dla" not in engine_index.wl.device_types:
            flags["dla_core"] = -1  # Force override
            flags["max_dlas"] = 0
        else:
            flags["dla_core"] = n_dlas - 1  # -1 falls back to max_dlas flag, which should be 0.
            flags["max_dlas"] = n_dlas

        if len(DETECTED_SYSTEM.accelerators[GPU]) > 1:
            flags["numa_config"] = numa_config_string(DETECTED_SYSTEM.get_numa_config())

        flags["scenario"] = engine_index.wl.scenario.valstr
        flags["model"] = engine_index.wl.benchmark.valstr

        if engine_index.wl.benchmark == Benchmark.Retinanet:
            flags["response_postprocess"] = "openimageeffnms"

        if engine_index.wl.system.extras["id"] == "L4x1":
            flags["eviction_last"] = 0.2

        return flags


@autoconfigure
@bind(Workload.FIELD)
@bind(harness_fields.audit_test)
class ResultSummaryOp(Operation):
    """Operation for generating result summaries from benchmark runs.

    This class handles the creation of metadata JSON files and accuracy checking
    for benchmark results.
    """

    @classmethod
    def immediate_dependencies(cls):
        """Get the immediate dependencies of this operation.

        Returns:
            set: Set of operation classes that this operation depends on.
        """
        return {BenchmarkHarnessOp}

    def __init__(self,
                 *args,
                 workload: Optional[Workload] = None,
                 audit_test: Optional[AuditTest] = None,
                 **kwargs):
        """Initialize the ResultSummaryOp.
        """
        super().__init__(*args, **kwargs)

        if workload is None:
            raise ValueError("Workload is required for ResultSummaryOp")
        self.wl = workload

        self.audit_test = audit_test

    def create_metadata_json(self,
                             log_dir: Path,
                             result_data: Dict[str, Any],
                             append: bool = False):
        """Create or update a metadata JSON file with benchmark results.

        Args:
            log_dir (Path): Directory to store the metadata file.
            result_data (Dict[str, Any]): Dictionary of result data to write.
            append (bool, optional): Whether to append to existing metadata. Defaults to False.
        """
        summary_file = log_dir / "metadata.json"
        if append and summary_file.exists():
            with summary_file.open(mode='r') as f:
                md = json.load(f)
                md.update(result_data)
        else:
            md = result_data

        if not os.environ.get('MLPERF_LOADGEN_LOGS_DIR'):
            with summary_file.open(mode="w") as f:
                json.dump(md, f, indent=4, sort_keys=True)

    def run(self, scratch_space, dependency_outputs):
        """Run the result summary operation.

        Args:
            scratch_space: The scratch space for temporary files.
            dependency_outputs: Outputs from dependency operations.

        Returns:
            dict: Dictionary containing the result metadata.
        """
        result_data = dependency_outputs[BenchmarkHarnessOp]["result_metadata"]

        if self.audit_test is not None:
            verifier = get_audit_verifier(self.audit_test)()
            audit_result = verifier.run()
            result_data["audit_result"] = audit_result
            result_data["audit_test"] = self.audit_test.valstr
            result_data["audit_success"] = (audit_result.split('_')[1].upper() == "PASS")

        self.create_metadata_json(self.wl.log_dir, result_data)
