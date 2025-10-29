# Copyright (c) 2025, NVIDIA CORPORATION. All rights reserved.
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

"""Configuration classes for LLM harness components."""

from __future__ import annotations
from code import G_BENCHMARK_MODULES
import dataclasses
from enum import Enum
import json
import logging
import os
from pathlib import Path
import yaml
import re
from typing import Any, Dict, List, Optional, Type

import code.common.constants as C
from code.common.gbs import GeneralizedBatchSize
from code.common.workload import Workload
from code.common.systems.system_list import DETECTED_SYSTEM
from code.fields import harness as harness_fields
from code.fields import general as gen_fields
from nvmitten.configurator import autoconfigure, bind
from nvmitten.json_utils import JSONable
from nvmitten.nvidia.accelerator import GPU

from . import fields as llm_fields
from .utils import get_yaml_string


def ignore_extra_kwargs(cls):
    """Decorator that allows dataclasses to ignore extra kwargs during initialization."""
    # First apply dataclass if not already applied
    if not hasattr(cls, '__dataclass_fields__'):
        cls = dataclasses.dataclass(cls)

    # Store the original __init__
    original_init = cls.__init__

    # Create a new __init__ that filters kwargs
    def __init__(self, **kwargs):
        # Get valid field names from the dataclass
        field_names = set(cls.__dataclass_fields__.keys())

        # Filter kwargs to only include known fields
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in field_names}
        ignored_kwargs = {k: v for k, v in kwargs.items() if k not in field_names}

        if ignored_kwargs:
            logging.debug(f"ignore_extra_kwargs: {cls.__name__} ignoring kwargs: {sorted(ignored_kwargs.keys())}")

        # Call original __init__ with filtered kwargs
        original_init(self, **filtered_kwargs)

    # Replace the __init__ method
    cls.__init__ = __init__

    return cls


@dataclasses.dataclass
class JSONSliceable(JSONable):
    """TRTLLM config.json files can contain arbitrary fields that vary depending on the model. Some
    fields are common and are used by our LLM Harness. Subclasses of TRTLLMConfig can specify which
    fields should be parsed from the config.json file.
    """

    _name_to_class = {}

    def __init_subclass__(cls, *args, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        JSONSliceable._name_to_class[cls.__name__] = cls

    @classmethod
    def type_from_name(cls, name: str) -> Type[JSONSliceable]:
        try:
            return JSONSliceable._name_to_class[name]
        except:
            return None

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> JSONSliceable:
        args = {}

        for f in dataclasses.fields(cls):
            if f.name not in d:
                continue

            # We can't directly check f.type here, since the `from __future__ import annotations`
            # changes the type of the fields to be a string with the class name instead of the
            # actual type.
            _type = f.type
            if not isinstance(_type, type):
                _type = JSONSliceable.type_from_name(_type)

            if isinstance(_type, type) and issubclass(_type, JSONSliceable):
                args[f.name] = _type.from_json(d[f.name])
            else:
                args[f.name] = d[f.name]
        return cls(**args)

    def to_json(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@ignore_extra_kwargs
@dataclasses.dataclass
class GenerationConfig(JSONSliceable):
    eos_token_id: int = 2
    bos_token_id: int = 1
    max_output_len: int = 1024
    min_output_len: int = 1
    name: str = "llama"
    runtime_beam_width: int = 1
    streaming: bool = True
    temperature: float = 1.0
    top_k: int = 1
    top_p: float = 0.001
    use_stop_tokens: bool = False

    @classmethod
    def from_file(cls, path: os.PathLike) -> GenerationConfig:
        """
        Load GenerationConfig from a JSON file.

        Args:
            path (os.PathLike): The path to the JSON file containing the generation configuration.

        Returns:
            GenerationConfig: The loaded GenerationConfig object.
        """
        with Path(path).open() as f:
            return cls.from_json(json.load(f)['generation_config'])


@autoconfigure
@bind(harness_fields.core_type, "_core_type")
@bind(llm_fields.tensor_parallelism)
@bind(llm_fields.pipeline_parallelism)
@bind(llm_fields.moe_expert_parallelism)
@bind(llm_fields.enable_ttft_latency_tracker)
@bind(llm_fields.show_steady_state_progress)
@bind(llm_fields.llm_gen_config_path, "gen_config_path")
@bind(gen_fields.log_dir)
@bind(llm_fields.capture_server_logs_dir)
@bind(Workload.FIELD, "workload")
@ignore_extra_kwargs
@dataclasses.dataclass
class HarnessConfig:
    # we make core_type a property to allow lazy import
    _core_type: harness_fields.CoreType = None
    tensor_parallelism: int = 1
    pipeline_parallelism: int = 1
    moe_expert_parallelism: int = None
    enable_ttft_latency_tracker: bool = False
    show_steady_state_progress: bool = False
    gen_config_path: str = None
    workload: Workload = None
    traffic_distribution_policy: str = None  # auto-assign based on workload
    log_dir: str = None
    capture_server_logs_dir: str = None

    gen_config: GenerationConfig = dataclasses.field(default_factory=GenerationConfig)
    random_seed: int = 0

    def __post_init__(self):
        if Path(self.gen_config_path).exists():
            self.gen_config = GenerationConfig.from_file(self.gen_config_path)

        # adjust streaming based on scenario
        self.gen_config.streaming &= (self.workload.scenario != C.Scenario.Offline)

        if self.capture_server_logs_dir is not None:
            self.capture_server_logs_dir = Path(self.capture_server_logs_dir)

        # override assign traffic distribution policy based on workload
        if self.traffic_distribution_policy is None:
            # TODO(vir): advanced load-balancing
            match self.workload.scenario:
                case C.Scenario.Server: self.traffic_distribution_policy = "load_balancing"
                case C.Scenario.Offline: self.traffic_distribution_policy = "round_robin"
                case _: self.traffic_distribution_policy = "round_robin"

    def get_instance_size(self) -> int:
        """ Get the size for given instance of this LLM. """
        num_gpus = self.tensor_parallelism
        if self.moe_expert_parallelism is None:
            num_gpus *= self.pipeline_parallelism

        else:
            if self.pipeline_parallelism > 1:
                # NOTE(vir): MOE_EP + PP not validated yet
                raise NotImplementedError()
            pass

        return num_gpus

    @property
    def core_type(self):
        """ FIXME(vir): WAR Lazy import the Workload DEFAULT CORE TYPE """
        if self._core_type is None:
            # use default core type if not specified
            self._core_type = G_BENCHMARK_MODULES[self.workload.benchmark].load(('DEFAULT_CORE_TYPE',)).DEFAULT_CORE_TYPE

        return self._core_type


# TRT-LLM Engine Configuration Classes


@dataclasses.dataclass
class PluginConfig(JSONSliceable):
    use_paged_context_fmha: bool = True


@dataclasses.dataclass
class BuildConfig(JSONSliceable):
    max_input_len: int = 1024
    max_seq_len: int = 2048
    max_batch_size: int = 1
    max_beam_width: int = 1
    max_num_tokens: int = 8192
    plugin_config: PluginConfig = dataclasses.field(default_factory=PluginConfig)


@dataclasses.dataclass
class Mapping(JSONSliceable):
    tp_size: int = 1
    pp_size: int = 1


@dataclasses.dataclass
class PretrainedConfig(JSONSliceable):
    mapping: Mapping = dataclasses.field(default_factory=Mapping)


@dataclasses.dataclass
class TRTLLMConfig(JSONSliceable):
    build_config: BuildConfig = dataclasses.field(default_factory=BuildConfig)
    pretrained_config: PretrainedConfig = dataclasses.field(default_factory=PretrainedConfig)


@dataclasses.dataclass
class TrtllmEngineConfig:
    engine_dir: os.PathLike
    trtllm_config: TRTLLMConfig = dataclasses.field(default_factory=TRTLLMConfig)

    @classmethod
    def from_engine_dir(cls, engine_dir: os.PathLike) -> TrtllmEngineConfig:
        """
        Load TrtllmEngineConfig from a directory containing a config.json file.

        Args:
            engine_dir (os.PathLike): The directory containing the engine configuration.

        Returns:
            TrtllmEngineConfig: The loaded TrtllmEngineConfig object.
        """
        config_file = Path(engine_dir) / 'config.json'
        assert config_file.exists(), f"TRTLLM Engine config file not found at: {config_file}"

        with config_file.open() as f:
            return cls(engine_dir, trtllm_config=TRTLLMConfig.from_json(json.load(f)))


# Backend-Specific Harness Configurations

class CheckpointType(Enum):
    """Enum for supported checkpoint types"""
    TRTLLM = "TRTLLM"
    HF = "HuggingFace"


@autoconfigure
@bind(llm_fields.trtllm_checkpoint_flags, "checkpoint_flags")
@bind(llm_fields.trtllm_build_flags, "build_flags")
@bind(llm_fields.trtllm_runtime_flags, "runtime_flags")
@bind(harness_fields.use_graphs, "use_cuda_graphs")
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmHarnessConfig(HarnessConfig):
    """Harness configuration shared by all TRT-LLM backends.
    This is singleton source of truth for trtllm flags in current workload.
    - checkpoint_flags: checkpoint and quantization flags
    - build_flags: engine flags
    - runtime_flags: runtime and harness flags
    """
    build_flags: Dict[str, Any] = dataclasses.field(default_factory=dict)
    runtime_flags: Dict[str, Any] = dataclasses.field(default_factory=dict)
    checkpoint_flags: Dict[str, Any] = dataclasses.field(default_factory=dict)

    use_cuda_graphs: bool = False

    DEFAULT_BUILD_FLAGS = {
        'max_beam_width': 1,
        'kv_cache_type': 'paged',
        'remove_input_padding': 'enable',
        'multiple_profiles': 'enable',
        'use_fused_mlp': 'enable',
        'context_fmha': 'enable',
        'max_num_tokens': None,
        'max_input_len': None,
        'max_seq_len': None,
        'use_fp8_context_fmha': 'enable',
        'use_paged_context_fmha': 'enable',
        'enable_attention_dp': None,
    }

    DEFAULT_RUNTIME_FLAGS = {
        'batch_scheduler_policy': 'max_util',
        'context_chunking_policy': 'first_come_first_served',
        'use_inflight_batching': True,
        'enable_batch_size_tuning': False,
        'enable_max_num_tokens_tuning': False,
        'dynamic_batch_moving_average_window': 128,
        'kvcache_free_gpu_mem_frac': 0.80,
        'enable_chunked_context': False,
        'exclude_input_from_output': True,

        # None means auto assign if possible else keep unassigned
        'max_batch_size': None,  # auto-assign (default: build max-batch-size)
        'max_num_tokens': None,  # auto-assign (default: build max-num-tokens)

        # cuda graphs flags
        'use_cuda_graphs': None,
        'cuda_graph_padding_enabled': False,
        'cuda_graph_batch_sizes': None,
    }

    DEFAULT_CHECKPOINT_FLAGS = {
        'kv_cache_dtype': None,
    }

    def __post_init__(self):
        super().__post_init__()
        self.build_flags = TrtllmHarnessConfig.DEFAULT_BUILD_FLAGS | self.build_flags
        self.runtime_flags = TrtllmHarnessConfig.DEFAULT_RUNTIME_FLAGS | self.runtime_flags
        self.checkpoint_flags = TrtllmHarnessConfig.DEFAULT_CHECKPOINT_FLAGS | self.checkpoint_flags

        self.build_flags['tensor_parallelism'] = self.tensor_parallelism
        self.build_flags['pipeline_parallelism'] = self.pipeline_parallelism
        self.build_flags['moe_expert_parallelism'] = self.moe_expert_parallelism
        self.runtime_flags["tensor_parallelism"] = self.tensor_parallelism
        self.runtime_flags["pipeline_parallelism"] = self.pipeline_parallelism
        self.runtime_flags["moe_expert_parallelism"] = self.moe_expert_parallelism

        self.runtime_flags['use_cuda_graphs'] = self.use_cuda_graphs

        if "max_batch_size" not in self.build_flags:
            self.build_flags["max_batch_size"] = GeneralizedBatchSize().e2e()

        # set runtime defaults from build flags
        for config in ["max_batch_size", "max_num_tokens"]:
            self.runtime_flags[config] = self.runtime_flags.get(config) or self.build_flags[config]


@autoconfigure
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmExecutorConfig(TrtllmHarnessConfig):
    """Configuration for TRT-LLM executor core """
    CHECKPOINT_T = CheckpointType.TRTLLM
    engine_dir: str = None
    engine_config: Optional[TrtllmEngineConfig] = None

    def __post_init__(self):
        super().__post_init__()

        # validate engine config flags
        self.engine_config = TrtllmEngineConfig.from_engine_dir(self.engine_dir)

        assert self.gen_config.runtime_beam_width <= self.engine_config.trtllm_config.build_config.max_beam_width
        assert self.gen_config.max_output_len <= (self.engine_config.trtllm_config.build_config.max_seq_len - self.engine_config.trtllm_config.build_config.max_input_len)

        assert self.build_flags['tensor_parallelism'] == self.engine_config.trtllm_config.pretrained_config.mapping.tp_size
        assert self.build_flags['pipeline_parallelism'] == self.engine_config.trtllm_config.pretrained_config.mapping.pp_size

        assert self.build_flags["max_batch_size"] == self.engine_config.trtllm_config.build_config.max_batch_size
        assert self.build_flags["max_num_tokens"] == self.engine_config.trtllm_config.build_config.max_num_tokens

        assert self.runtime_flags["max_batch_size"] <= self.build_flags["max_batch_size"]
        assert self.runtime_flags["max_num_tokens"] <= self.build_flags["max_num_tokens"]


@autoconfigure
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmExtraYAMLConfig(TrtllmHarnessConfig):
    """Base configuration for TRT-LLM high-level cores that need extra YAML config"""
    model_path: str = None  # model weights path, loaded from mitten pipeline or CLI override of --llm_quantizer_outdir

    # these are auto-configured in post_init
    extra_config_yaml: str = None

    DEFAULT_EXTRA_CONFIG = {
        # NOTE(vir): for now these apply only in pytorch backend
        'print_iter_log': True,
        'enable_layerwise_nvtx_marker': False,
        'stream_interval': 1,
        'disable_overlap_scheduler': False,
        'enable_iter_perf_stats': True,  # enable /metrics endpoint for trtllm iter stats
    }

    # TODO(vir): allow recursive dicts
    DEFAULT_RUNTIME_FLAGS = {
        # None means auto assign if possible else keep unassigned
        'trtllm_backend': 'pytorch',  # can be pytorch or cpp

        # can be ["CUTLASS", "CUTEDSL", "WIDEEP", "TRTLLM", "VANILLA"]
        'moe_backend': 'CUTLASS',

        # only used when attention-dp is enabled
        # defaults to TRUE
        'adp_balancing_enable': True,
        'adp_balancing_batching_wait_iters': 10,
        'adp_balancing_timeout_iters': 500,
    }

    DEFAULT_BUILD_FLAGS = {
        'torch_compile_enabled': None,
    }

    def __post_init__(self):
        super().__post_init__()
        self.build_flags = TrtllmExtraYAMLConfig.DEFAULT_BUILD_FLAGS | self.build_flags
        self.runtime_flags = TrtllmExtraYAMLConfig.DEFAULT_RUNTIME_FLAGS | self.runtime_flags

        # default cuda_graph_batch_sizes to powers of 2 upto max-batch-size
        # enable with harness_fields.use_cuda_graphs
        if self.runtime_flags['use_cuda_graphs'] and self.runtime_flags.get('cuda_graph_batch_sizes') is None:
            default_capture_sizes = [1 << i for i in range(self.build_flags['max_batch_size'].bit_length())]
            self.runtime_flags['cuda_graph_batch_sizes'] = default_capture_sizes

        # set values for extra config YAML
        self.runtime_flags['batch_scheduler_policy'] = {
            'max_util': 'MAX_UTILIZATION',
            'no_evict': 'GUARANTEED_NO_EVICT',
            'static': 'STATIC_BATCH',
            # None means unspecified
        }.get(self.runtime_flags['batch_scheduler_policy'])

        self.runtime_flags['context_chunking_policy'] = {
            'equal_progress': 'EQUAL_PROGRESS',
            'first_come_first_served': 'FIRST_COME_FIRST_SERVED',
            # None means unspecified
        }.get(self.runtime_flags['context_chunking_policy'])

        self.extra_config_yaml = self._generate_extra_config_yaml(self.runtime_flags, self.checkpoint_flags, self.build_flags)

    @classmethod
    def _generate_extra_config_yaml(cls,
                                    runtime_flags: Dict[str, Any],
                                    checkpoint_flags: Dict[str, Any],
                                    build_flags: Dict[str, Any]):
        """
        Generate YAML content for trtllm-serve extra configurations file.

        Args:
            runtime_flags: Runtime configuration flags
            checkpoint_flags: Checkpoint configuration flags
            build_flags: Build configuration flags

        Returns:
            str: YAML formatted configuration content
        """
        config_dict = {}

        using_pytorch = runtime_flags['trtllm_backend'] == 'pytorch'
        if using_pytorch:
            config_dict |= {**cls.DEFAULT_EXTRA_CONFIG}

        config_dict |= {
            'enable_chunked_prefill': runtime_flags['enable_chunked_context'],
            'scheduler_config': {
                'capacity_scheduler_policy': runtime_flags['batch_scheduler_policy'],
                'context_chunking_policy': runtime_flags['context_chunking_policy'],
            },

            'kv_cache_dtype': checkpoint_flags['kv_cache_dtype'],
            'kv_cache_config': {
                'free_gpu_memory_fraction': runtime_flags['kvcache_free_gpu_mem_frac'],
                'enable_block_reuse': False,
            },

            'enable_attention_dp': build_flags['enable_attention_dp'],
        }

        if using_pytorch:
            config_dict |= {
                'torch_compile_enabled': build_flags['torch_compile_enabled'],
                'use_cuda_graph': runtime_flags['use_cuda_graphs'],
                'moe_backend': runtime_flags['moe_backend'],
            }

            if config_dict['use_cuda_graph']:
                assert runtime_flags['cuda_graph_batch_sizes'] is not None, \
                    logging.error(f"CUDA graphs enabled but no cuda_graph_batch_sizes provided. ")

                config_dict |= {
                    'cuda_graph_padding_enabled': runtime_flags['cuda_graph_padding_enabled'],
                    'cuda_graph_batch_sizes': runtime_flags['cuda_graph_batch_sizes'],

                    # NOTE(vir): we dont rely on automatic batch-sizes
                    # 'cuda_graph_max_batch_size': 0
                }

            if config_dict['enable_attention_dp'] and runtime_flags['adp_balancing_enable']:
                config_dict |= {
                    'attention_dp_config': {
                        'enable_balance': runtime_flags['adp_balancing_enable'],
                        'batching_wait_iters': runtime_flags['adp_balancing_batching_wait_iters'],
                        'timeout_iters': runtime_flags['adp_balancing_timeout_iters'],
                    }
                }

        if not using_pytorch and runtime_flags['use_cuda_graphs']:
            raise NotImplementedError("CUDA Graphs are not supported in TRT/C++ backend yet.")

        # create file content string
        yaml_content = get_yaml_string(config_dict)
        return yaml_content

    def get_model_repo(self):
        return G_BENCHMARK_MODULES[self.workload.benchmark].load(("HF_MODEL_REPO",)).HF_MODEL_REPO


@autoconfigure
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmHlApiConfig(TrtllmExtraYAMLConfig):
    """Configuration for TRT-LLM high-level API core"""
    pass


@autoconfigure
@bind(llm_fields.trtllm_server_urls, "trtllm_endpoint_urls")
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmEndpointConfig(TrtllmExtraYAMLConfig):
    """Configuration for TrtllmEndpointCore"""
    CHECKPOINT_T = CheckpointType.HF

    trtllm_endpoint_urls: Optional[List[str]] = None
    endpoint_url: str = "0.0.0.0:30000"

    is_mpi_task: bool = False
    global_size: Optional[int] = None

    DEFAULT_RUNTIME_FLAGS = {
        'num_postprocess_workers': 2,
        'workers_per_core': 2,  # default worker processes per core / endpoint
        'http_backend': 'custom_http',  # can be custom_http or openai_async
        'max_concurrency': None,  # auto-assign (default: build max-batch-size)
    }

    def __post_init__(self):
        super().__post_init__()
        self.runtime_flags = TrtllmEndpointConfig.DEFAULT_RUNTIME_FLAGS | self.runtime_flags
        self.runtime_flags['workers_per_core'] = int(self.runtime_flags['workers_per_core'])

        if self.runtime_flags['max_concurrency'] is None:
            # max_concurrency applies to each LLMCore (ie each data-parallel rank) of inference
            concurrency = self.build_flags['max_batch_size']

            if self.build_flags['enable_attention_dp']:
                # since max-bs applies per attention-rank,
                # when enabled, each TP rank has a DP rank of attention block
                concurrency *= self.tensor_parallelism * concurrency

            self.runtime_flags['max_concurrency'] = int(concurrency)
        else:
            # convert to int if needed
            self.runtime_flags['max_concurrency'] = int(self.runtime_flags['max_concurrency'])

        # detect mpi world, when launched in leader mode
        if global_size := os.environ.get('SLURM_NTASKS', os.environ.get('OMPI_COMM_WORLD_SIZE', None)):
            self.is_mpi_task = True
            self.global_size = int(global_size)

        # NOTE(vir):
        # we have full world visibility in trtllm-serve only in single-NODE orchestrator mode
        # so we are able to spawn all erquired local DP ranks using subprocess
        if self.trtllm_endpoint_urls is None and self.__class__ is TrtllmEndpointConfig:
            num_local_gpus = len(DETECTED_SYSTEM.accelerators[GPU])
            worker_size = self.get_instance_size()
            num_dp_ranks = num_local_gpus // worker_size
            self.trtllm_endpoint_urls = [
                self._get_endpoint_url(dp_index)
                for dp_index in range(num_dp_ranks)
            ]

    def _get_endpoint_url(self, dp_index: int = 0) -> str:
        assert not self.is_mpi_task, "Must be called in ORCHESTRATOR Mode (single-node NON mpi)"
        base_port = 30000
        port = base_port + dp_index
        local_node_name = "0.0.0.0"
        return f"{local_node_name}:{port}"


@autoconfigure
@bind(llm_fields.trtllm_disagg_config_path, "disagg_config_path")
@ignore_extra_kwargs
@dataclasses.dataclass
class TrtllmDisaggEndpointConfig(TrtllmEndpointConfig):
    """Configuration for TrtllmEndpointCore with trtllm-serve-diagg endpoint"""
    CHECKPOINT_T = CheckpointType.HF

    DEFAULT_RUNTIME_FLAGS = {
        # ctx
        'num_ctx_servers': 1,
        'ctx_tp_size': 1,
        'ctx_batch_size': 1,
        'ctx_max_num_tokens': 8192,
        'ctx_enable_attention_dp': False,

        # gen
        'num_gen_servers': 1,
        'gen_tp_size': 1,
        'gen_batch_size': 1,
        'gen_max_num_tokens': 8192,
        'gen_enable_attention_dp': False,
        'gen_gpu_memory_fraction': 0.8,

        'worker_start_port': 8336,
        'server_port': 30000,
        'enable_pdl': 1,
        'nsys_on': 0,
    }

    disagg_config_path: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        self.runtime_flags = TrtllmDisaggEndpointConfig.DEFAULT_RUNTIME_FLAGS | self.runtime_flags

        # load disagg config path if provided
        if self.disagg_config_path and Path(self.disagg_config_path).exists():
            logging.info(f"Loading disagg config from {self.disagg_config_path}")

            if self.trtllm_endpoint_urls is not None:
                logging.info("Overriding trtllm_endpoint_urls from disagg config file")

            # get key hostname and port from disagg_config if given
            config_yaml = yaml.safe_load(Path(self.disagg_config_path).read_text())
            hostname = config_yaml.get('hostname')
            port = config_yaml.get('port')
            assert hostname is not None and port is not None, f"Invalid disagg config file at: {self.disagg_config_path}. Expected keys: 'hostname' and 'port'."
            self.runtime_flags['server_port'] = port
            self.trtllm_endpoint_urls = [f'{hostname}:{port}']

        # assure mpirun -n <num_ranks> is feasible (sindle-node leader mode)
        if self.is_mpi_task and (single_node_mpi := os.environ.get('SLURM_JOB_NODELIST', False)):
            num_local_gpus = len(DETECTED_SYSTEM.accelerators[GPU])
            assert self.global_size is not None, "MPI/SLURM-NTASKS world not detected."
            assert self.global_size <= num_local_gpus, f"Launched more ranks ({self.global_size}) than local_gpus ({num_local_gpus})"

        # update port based on configured urls
        if self.trtllm_endpoint_urls is not None:
            match = re.match(r"^(?P<host>.*):(?P<port>\d+)$", self.trtllm_endpoint_urls[0])
            assert match, f"Invalid trtllm_endpoint_urls format: {self.trtllm_endpoint_urls[0]}"
            self.runtime_flags['server_port'] = int(match.group('port'))

        # TODO(vir): enable orchestrator mode DP
        if not self.is_mpi_task and \
                (self.trtllm_endpoint_urls is not None and len(self.trtllm_endpoint_urls) > 1):
            raise NotImplementedError("Orchestrator mode DP of disagg endpoints is not yet enabled")

        # TODO(vir): generate config file inline (instead of TRTLLM gen_yaml.py)
        # # collect all flags from trtllm_runtime_flags with __disagg_ctx__ prefix in their key
        # context_runtime_flags = {
        #     k.replace('__disagg_ctx__', ''): v
        #     for k, v in self.runtime_flags.items()
        #     if k.startswith('__disagg_ctx__')
        # }
        #
        # # collect all flags from trtllm_runtime_flags with __disagg_gen__ prefix in their key
        # gen_runtime_flags = {
        #     k.replace('__disagg_gen__', ''): v
        #     for k, v in self.runtime_flags.items()
        #     if k.startswith('__disagg_gen__')
        # }
        #
        # self.context_extra_config_yaml = self._generate_extra_config_yaml(self.runtime_flags, self.checkpoint_flags, self.build_flags)
        # self.gen_extra_config_yaml = self._generate_extra_config_yaml(self.runtime_flags, self.checkpoint_flags, self.build_flags)

        return

    def get_instance_size(self) -> int:
        num_ctx_gpus = self.runtime_flags['ctx_tp_size'] * self.runtime_flags['num_ctx_servers']
        num_gen_gpus = self.runtime_flags['ctx_tp_size'] * self.runtime_flags['num_ctx_servers']
        return num_ctx_gpus + num_gen_gpus


@autoconfigure
@bind(llm_fields.triton_server_urls)
@ignore_extra_kwargs
@dataclasses.dataclass
class TritonHarnessConfig(TrtllmHarnessConfig):
    """Configuration specific to Triton gRPC core"""
    CHECKPOINT_T = CheckpointType.TRTLLM
    server_url: str = "0.0.0.0:8001"
    clients_per_server: int = 1
    models_per_server: int = 1
    # NOTE(vir): we should add engine_path | config here

    triton_server_urls: Optional[List[str]] = None

    def __post_init__(self):
        super().__post_init__()

        # validate and set default values
        if self.triton_server_urls is not None:
            assert len(self.triton_server_urls) == self.get_num_endpoints(), \
                f"Please specify {self.get_num_endpoints()} URLs in `--triton_server_urls` field, got {len(self.triton_server_urls)}"

        else:
            # calculate default endpoints
            self.triton_server_urls = [
                self.get_endpoint_url_for_dp(index)
                for index in range(self.get_num_endpoints())
            ]

    def get_num_endpoints(self) -> int:
        """ Get the number of triton server commands to launch based on overall world size. """
        num_local_gpus = len(DETECTED_SYSTEM.accelerators[GPU])
        worker_size = self.get_instance_size()
        num_endpoints = 1

        if global_size := os.environ.get('SLURM_NTASKS', os.environ.get('OMPI_COMM_WORLD_SIZE', None)):
            global_size = int(global_size)
            assert global_size % worker_size == 0, f"Global size SLURM_NTASKS|OMPI_COMM_WORLD_SIZE=({global_size}) must be divisible by worker size ({worker_size})"
            num_endpoints = global_size // worker_size

        else:
            assert num_local_gpus % worker_size == 0, f"Number of local GPUs ({num_local_gpus}) must be divisible by worker size ({worker_size})"
            num_endpoints = num_local_gpus // worker_size

        # we launch 1 triton  endpoint per model dp rank
        return num_endpoints

    def get_endpoint_url_for_dp(self, dp_rank: Optional[int]) -> str:
        """
        Get the endpoint URL for a specific MPI-rank.
        """
        if self.triton_server_urls is not None:
            return self.triton_server_urls[dp_rank]

        base_port = 8000
        port = base_port + dp_rank
        return f"0.0.0.0:{port}"
