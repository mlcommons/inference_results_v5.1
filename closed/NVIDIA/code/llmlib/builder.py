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


from code import G_BENCHMARK_MODULES
import dataclasses
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from code.common.constants import Benchmark
from code.common import paths
from code.common.constants import Precision
from code.common.workload import ComponentEngine, EngineIndex, Workload
from code.fields import gen_engines as builder_fields
from code.fields import models as model_fields
from nvmitten.configurator import HelpInfo, autoconfigure, bind
from nvmitten.pipeline import Operation

from . import fields as llm_fields
from .utils import prefix_logger as logging


"""TRTLLM execution has 3 stages:
1. Quantization (also known as "checkpoint building")
2. Engine building
3. Running the harness via TRTLLM Executor
"""


@autoconfigure
@bind(llm_fields.trtllm_lib_path, "lib_path")
@bind(llm_fields.tensor_parallelism, "tp_size")
@bind(llm_fields.pipeline_parallelism, "pp_size")
@dataclasses.dataclass
class TRTLLMLibraryLoader:
    """
    Loads the TRTLLM library and provides a callable interface to execute TRTLLM commands.
    """

    lib_path: os.PathLike = paths.BUILD_DIR / "TRTLLM"
    tp_size: int = 1
    pp_size: int = 1

    world_size: int = dataclasses.field(init=False)

    def __post_init__(self):
        assert self.lib_path is not None, "lib_path is required"
        self.lib_path = Path(self.lib_path)
        assert self.lib_path.exists(), f"TRTLLM library not found at: {self.lib_path}"

        self.world_size = self.tp_size * self.pp_size
        assert self.world_size > 0, "world_size must be greater than 0"

    def __call__(self,
                 main_path: str,
                 argv: List[str],
                 python_bin: str = sys.executable,
                 log_dir: Optional[os.PathLike] = None,
                 custom_env: Optional[Dict[str, Any]] = None) -> Tuple[subprocess.CompletedProcess, float]:
        cmd = [python_bin, main_path] + argv
        logging.info(f"Command executing in {self.lib_path}: {' '.join(cmd)}")

        env = os.environ.copy()
        if custom_env is not None:
            env.update(custom_env)

        tik = time.time()
        ret = subprocess.run(cmd,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             text=True,
                             cwd=str(self.lib_path),
                             env=env)
        tok = time.time()

        if log_dir is not None:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            # Save stdout and stderr logs
            with (log_dir / 'stdout.txt').open(mode='w') as f:
                f.write(ret.stdout)
            with (log_dir / 'stderr.txt').open(mode='w') as f:
                f.write(ret.stderr)

        return ret, (tok - tik)


@autoconfigure
@bind(model_fields.model_path)
@bind(llm_fields.quantizer_outdir, "output_path")
@bind(builder_fields.calib_data_dir, "dataset_path")
@bind(builder_fields.calib_batch_size, "batch_size")
@bind(builder_fields.calib_max_batches, "max_batches")
@bind(model_fields.precision, "dtype_out")
@bind(llm_fields.trtllm_checkpoint_flags, "flags")
@dataclasses.dataclass
class QuantizerConfig:
    model_path: Optional[os.PathLike] = None
    output_path: Optional[os.PathLike] = None
    dataset_path: Optional[os.PathLike] = None
    batch_size: int = 1024
    max_batches: int = 1
    dtype_in: Precision = Precision.FP16
    dtype_out: Precision = Precision.FP8

    flags: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        assert self.model_path is not None, "model_path is required"
        self.model_path = Path(self.model_path)
        assert self.model_path.exists(), f"Model not found at: {self.model_path}"

        assert self.dataset_path is not None, "dataset_path is required"
        self.dataset_path = Path(self.dataset_path)

        assert self.output_path is not None, "output_path is required"
        self.output_path = Path(self.output_path)

        if self.dtype_out == Precision.FP4:
            logging.info("Using NVFP4 for FP4 quantization")
            self.dtype_out = Precision.NVFP4

        if override := os.environ.get("TRTLLM_CHECKPOINT_FLAGS", None):
            self.flags |= llm_fields.parse_trtllm_flags(override)
        if "qformat" in self.flags:
            raise KeyError(f"'qformat' should not be specified in TRTLLM flags. Use --{model_fields.precision.name} instead.")


@autoconfigure
@bind(Workload.FIELD)
@bind(llm_fields.quantizer_lib_path_override, "lib_path")
@bind(builder_fields.force_calibration, "force")
class TRTLLMQuantizerOp(Operation):
    @classmethod
    def immediate_dependencies(cls):
        return None

    @classmethod
    def output_keys(cls):
        return ["quantized_checkpoint_path"]

    def __init__(self,
                 *args,
                 workload: Optional[Workload] = None,
                 lib_path: Optional[os.PathLike] = None,
                 script_path: os.PathLike = Path("examples/quantization/quantize.py"),
                 quantizer_config: Optional[QuantizerConfig] = None,
                 force: bool = False,
                 **kwargs):
        super().__init__(*args, **kwargs)

        assert workload is not None, "Workload is required"
        self.wl = workload

        if quantizer_config is None:
            if hasattr(_mod := G_BENCHMARK_MODULES[self.wl.benchmark].load(), "QuantizerConfig"):
                self.quantizer_config = _mod.QuantizerConfig()
            else:
                self.quantizer_config = QuantizerConfig()
        else:
            self.quantizer_config = quantizer_config

        if lib_path:
            self.trtllm_loader = TRTLLMLibraryLoader(lib_path=lib_path)
        else:
            self.trtllm_loader = TRTLLMLibraryLoader()

        self.force = force
        self.script_path = Path(script_path)
        if not (script_location := self.trtllm_loader.lib_path / script_path).exists():
            raise FileNotFoundError(f"Could not locate TRTLLM quantization script at: {script_location}")

        self.custom_env = None

    def get_cli_flags(self) -> List[str]:
        _d = {"tp_size": self.trtllm_loader.tp_size,
              "pp_size": self.trtllm_loader.pp_size,
              "model_dir": str(self.quantizer_config.model_path.absolute()),
              "output_dir": str(self.quantizer_config.output_path.absolute()),
              "calib_dataset": str(self.quantizer_config.dataset_path.absolute()),
              "calib_size": self.quantizer_config.batch_size * self.quantizer_config.max_batches,
              "dtype": "float16" if self.quantizer_config.dtype_in == Precision.FP16 else "bfloat16",
              "qformat": self.quantizer_config.dtype_out.valstr.lower()}
        _d |= self.quantizer_config.flags

        return [f"--{k}={v}" for k, v in _d.items() if v is not None]

    def run(self, scratch_space, dependency_outputs):
        out_dir = self.quantizer_config.output_path.absolute()
        if not self.force and out_dir.exists():
            logging.info(f"Quantized checkpoint already exists at: {out_dir}. Set --force_calibration to overwrite.")
            return {"quantized_checkpoint_path": out_dir}

        if not out_dir.exists():
            out_dir.mkdir(parents=True)

        ret, duration = self.trtllm_loader(str(self.script_path),
                                           self.get_cli_flags(),
                                           python_bin=self.wl.benchmark.python_path,
                                           log_dir=out_dir,
                                           custom_env=self.custom_env)

        if ret.returncode != 0:
            logging.error(ret.stderr)
            raise RuntimeError(f"Quantization failed. Logs dumped to: {out_dir}")

        logging.info(f"Quantization complete in {duration}s. Saved to: {out_dir}")
        return {"quantized_checkpoint_path": out_dir}


HelpInfo.add_configurator_dependencies(TRTLLMQuantizerOp,
                                       {QuantizerConfig, TRTLLMLibraryLoader})


@autoconfigure
@bind(Workload.FIELD)
@bind(builder_fields.force_calibration, "force")
@bind(llm_fields.quantizer_outdir, "output_path")
class HFQuantizerOp(Operation):

    SCRIPT_QUANTIZABLE_BENCHMARKS = [Benchmark.LLAMA2]

    @classmethod
    def immediate_dependencies(cls):
        return None

    @classmethod
    def output_keys(cls):
        return ["quantized_checkpoint_path"]

    def __init__(self,
                 *args,
                 workload: Optional[Workload] = None,
                 lib_path: Optional[os.PathLike] = Path("/work/code/llmlib"),
                 script_path: os.PathLike = Path("hf_quantize.py"),
                 quantizer_config: Optional[QuantizerConfig] = None,
                 force: bool = False,
                 output_path: Optional[os.PathLike] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)

        assert workload is not None, "Workload is required"
        self.wl = workload

        if quantizer_config is None:
            if hasattr(_mod := G_BENCHMARK_MODULES[self.wl.benchmark].load(), "QuantizerConfig"):
                self.quantizer_config = _mod.QuantizerConfig()
            else:
                self.quantizer_config = QuantizerConfig()
        else:
            self.quantizer_config = quantizer_config

        # Technically not TRTLLM loader, but reusing the code
        self.trtllm_loader = TRTLLMLibraryLoader(lib_path=lib_path)
        self.script_path = Path(script_path)
        if not (script_location := self.trtllm_loader.lib_path / script_path).exists():
            raise FileNotFoundError(f"Could not locate HF quantization script at: {script_location}")

        assert self.quantizer_config.hf_output_path is not None, "hf_output_path is required"

        self.force = force
        self.custom_env = None

    def get_cli_flags(self) -> List[str]:
        _d = {"model_dir": str(self.quantizer_config.model_path.absolute()),
              "output_dir": str(self.quantizer_config.hf_output_path.absolute()),
              "calib_dataset": str(self.quantizer_config.dataset_path.absolute()),
              "calib_size": self.quantizer_config.batch_size * self.quantizer_config.max_batches,
              "dtype": "float16" if self.quantizer_config.dtype_in == Precision.FP16 else "bfloat16",
              "qformat": self.quantizer_config.dtype_out.valstr.lower()}
        _d |= self.quantizer_config.flags

        return [f"--{k}={v}" for k, v in _d.items() if v is not None]

    def run(self, scratch_space, dependency_outputs):
        out_dir = self.quantizer_config.hf_output_path.absolute()
        if not self.force and out_dir.exists():
            logging.info(f"Quantized checkpoint already exists at: {out_dir}. Set --force_calibration to overwrite.")
            return {"quantized_checkpoint_path": out_dir}

        if self.wl.benchmark not in self.SCRIPT_QUANTIZABLE_BENCHMARKS:
            raise ValueError(f"{self.wl.benchmark} cannot be quantized by the script. Please follow <workload>/README.md to download the checkpoint and place it at {out_dir}.")

        if not out_dir.exists():
            out_dir.mkdir(parents=True)

        ret, duration = self.trtllm_loader(str(self.script_path),
                                           self.get_cli_flags(),
                                           python_bin=self.wl.benchmark.python_path,
                                           log_dir=out_dir,
                                           custom_env=self.custom_env)

        if ret.returncode != 0:
            logging.error(ret.stderr)
            raise RuntimeError(f"Quantization failed. Logs dumped to: {out_dir}")

        logging.info(f"Quantization complete in {duration}s. Saved to: {out_dir}")
        return {"quantized_checkpoint_path": out_dir}


HelpInfo.add_configurator_dependencies(HFQuantizerOp, {QuantizerConfig})


@autoconfigure
@bind(llm_fields.tensor_parallelism, "tp_size")
@bind(llm_fields.pipeline_parallelism, "pp_size")
@dataclasses.dataclass
class LLMComponentEngine(ComponentEngine):
    tp_size: int = 1
    pp_size: int = 1

    def __post_init__(self):
        assert self.tp_size > 0, "tp_size must be greater than 0"
        assert self.pp_size > 0, "pp_size must be greater than 0"

    @property
    def fname(self) -> str:
        base = '-'.join([self.device_type,
                         self.precision.valstr,
                         f"b{self.batch_size}",
                         f"tp{self.tp_size}",
                         f"pp{self.pp_size}"])
        return f"{base}.{self.setting.short}"


@autoconfigure
@bind(llm_fields.trtllm_lib_path, "lib_path")
@bind(llm_fields.trtllm_build_flags, "build_flags")
@bind(builder_fields.force_build_engines, "force")
class TRTLLMBuilderOp(Operation):
    @classmethod
    def immediate_dependencies(cls):
        return {TRTLLMQuantizerOp}

    @classmethod
    def output_keys(cls):
        return ["engine_dir"]

    def __init__(self,
                 *args,
                 lib_path: os.PathLike = paths.BUILD_DIR / "TRTLLM",
                 script_path: os.PathLike = Path("tensorrt_llm/commands/build.py"),
                 build_flags: Optional[Dict[str, Any]] = {},
                 force: bool = False,
                 **kwargs):
        super().__init__(*args, **kwargs)

        self.engine_index = EngineIndex()
        self.wl = self.engine_index.wl
        self.max_batch_size = self.engine_index.bs_info.e2e()
        self.force = force

        self.trtllm_loader = TRTLLMLibraryLoader(lib_path=lib_path)
        self.script_path = Path(script_path)
        if not (script_location := self.trtllm_loader.lib_path / script_path).exists():
            raise FileNotFoundError(f"Could not locate TRTLLM build script at: {script_location}")

        self.build_flags = build_flags
        if override := os.environ.get("TRTLLM_BUILD_FLAGS", None):
            self.build_flags |= llm_fields.parse_trtllm_flags(override)

        if "tensor_parallelism" in self.build_flags:
            raise KeyError(f"'tensor_parallelism' should not be specified in TRTLLM flags. Use --{llm_fields.tensor_parallelism.name} instead.")
        if "pipeline_parallelism" in self.build_flags:
            raise KeyError(f"'pipeline_parallelism' should not be specified in TRTLLM flags. Use --{llm_fields.pipeline_parallelism.name} instead.")
        if "max_batch_size" in self.build_flags and not "whisper" in self.wl.benchmark.valstr:
            raise KeyError(f"'max_batch_size' should not be specified in TRTLLM flags. Use --gpu_batch_size instead.")

    def get_cli_flags(self) -> List[str]:
        _d = {
            "workers": self.trtllm_loader.world_size if self.trtllm_loader.world_size > 1 else None,
            "max_batch_size": self.max_batch_size,
        }
        _d |= self.build_flags

        # At this point, _d should only contain Python primitives
        # Assume that all TRTLLM build.py flags assume fp4 means nvfp4
        for k, v in _d.items():
            if isinstance(v, str) and _d[k].lower() == 'fp4':
                _d[k] = 'nvfp4'

        return [f"--{k}={v}" for k, v in _d.items() if v is not None]

    def run(self, scratch_space, dependency_outputs):
        ckpt_path = dependency_outputs[TRTLLMQuantizerOp]["quantized_checkpoint_path"]
        assert ckpt_path.exists(), f"Quantized checkpoint not found at: {ckpt_path}"
        assert (ckpt_path / 'rank0.safetensors').exists(), f"rank0.safetensors not found at: {ckpt_path}"

        assert len(self.engine_index.engines) == 1, "TRTLLMBuilderOp only supports single engine"
        c_eng = self.engine_index.engines[0]
        out_dir = self.engine_index.full_path(c_eng)
        if not self.force and out_dir.exists():
            logging.info(f"Engine already exists at: {out_dir}. Set --force_build_engines to overwrite.")
            return {"engine_dir": out_dir}
        elif not out_dir.exists():
            out_dir.mkdir(parents=True)

        argv = [f'--checkpoint_dir={str(ckpt_path.absolute())}',
                f'--output_dir={str(out_dir.absolute())}'] + self.get_cli_flags()
        ret, duration = self.trtllm_loader(str(self.script_path),
                                           argv,
                                           python_bin=self.wl.benchmark.python_path,
                                           log_dir=out_dir)

        if ret.returncode != 0:
            logging.error(ret.stderr)
            raise RuntimeError(f"Engine build failed. Logs dumped to: {out_dir}")

        logging.info(f"Engine build complete in {duration}s. Saved to: {out_dir}")
        return {"engine_dir": out_dir}


HelpInfo.add_configurator_dependencies(TRTLLMBuilderOp,
                                       {EngineIndex, TRTLLMLibraryLoader})
