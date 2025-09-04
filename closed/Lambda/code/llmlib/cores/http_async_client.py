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

"""
HTTP client for concurrent LLM request execution on OpenAI Endpoint.
Lightweight wrapper of aiohttp for HTTP requests, uses ZeroMQ for IPC in multiprocess mode.
"""

from __future__ import annotations
import asyncio
import atexit
import logging
import multiprocessing as mp
import signal
import time
import os
import uuid
from typing import List, Optional, Dict, Any

import aiohttp
import orjson
import pickle
import struct
import numpy as np
import zmq
import zmq.asyncio
import uvloop
uvloop.install()
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

from tokenizers import Tokenizer as AutoTokenizer

from ..config import TrtllmEndpointConfig
from .base import LLMRequest, LLMResponse
from .mp_worker_utils import WorkerProcessManager


def _np_serialize_request(request_dict):
    """
    Serialize request data using numpy for integer lists.
    Protocol: [header(4 bytes)][request_id_len(4 bytes)][request_id][input_tokens_data][stop_tokens_data]
    """
    parts = []

    # Header: version (1 byte) + reserved (3 bytes)
    parts.append(struct.pack('!B3x', 1))  # Version 1

    # Request ID - handle both string and integer types
    request_id = request_dict['request_id']
    if isinstance(request_id, int):
        request_id_bytes = str(request_id).encode('utf-8')
    else:
        request_id_bytes = request_id.encode('utf-8')
    parts.append(struct.pack('!I', len(request_id_bytes)))
    parts.append(request_id_bytes)

    # Input tokens
    input_tokens = request_dict['input_tokens']
    if input_tokens is None:
        parts.append(struct.pack('!I', 0))
    else:
        arr = np.array(input_tokens, dtype=np.int32)
        parts.append(struct.pack('!I', len(arr)))
        parts.append(arr.tobytes())

    # Stop tokens
    stop_tokens = request_dict.get('stop_tokens')
    if stop_tokens is None:
        parts.append(struct.pack('!I', 0))
    else:
        arr = np.array(stop_tokens, dtype=np.int32)
        parts.append(struct.pack('!I', len(arr)))
        parts.append(arr.tobytes())

    return b''.join(parts)


def _np_deserialize_request(data):
    """ Deserialize request data using numpy for integer lists. """
    offset = 0

    # Read header
    version, = struct.unpack_from('!B', data, offset)
    offset += 4

    if version != 1:
        raise ValueError(f"Unsupported protocol version: {version}")

    # Read request ID
    request_id_len, = struct.unpack_from('!I', data, offset)
    offset += 4
    request_id_str = data[offset:offset + request_id_len].decode('utf-8')
    offset += request_id_len

    # Convert back to int if it looks like an integer
    try:
        request_id = int(request_id_str)
    except ValueError:
        request_id = request_id_str

    # Read input tokens
    input_tokens_len, = struct.unpack_from('!I', data, offset)
    offset += 4
    if input_tokens_len > 0:
        input_tokens = np.frombuffer(data, dtype=np.int32, count=input_tokens_len, offset=offset).tolist()
        offset += input_tokens_len * 4
    else:
        input_tokens = []

    # Read stop tokens
    stop_tokens_len, = struct.unpack_from('!I', data, offset)
    offset += 4
    if stop_tokens_len > 0:
        stop_tokens = np.frombuffer(data, dtype=np.int32, count=stop_tokens_len, offset=offset).tolist()
    else:
        stop_tokens = []

    return {
        'request_id': request_id,
        'input_tokens': input_tokens,
        'stop_tokens': stop_tokens
    }


def _np_serialize_response(response_dict):
    """
    Serialize response data using numpy for integer lists.
    Protocol: [header(4 bytes)][request_id_len(4 bytes)][request_id][is_final(1 byte)][error_len(4 bytes)][error][tokens_data]
    """
    # Convert output_tokens to numpy array if it's a list of lists of integers
    output_tokens = response_dict['output_tokens']

    # Build the message parts
    parts = []

    # Header: version (1 byte) + reserved (3 bytes)
    parts.append(struct.pack('!B3x', 1))  # Version 1

    # Request ID - handle both string and integer types
    request_id = response_dict['request_id']
    if isinstance(request_id, int):
        request_id_bytes = str(request_id).encode('utf-8')
    else:
        request_id_bytes = request_id.encode('utf-8')
    parts.append(struct.pack('!I', len(request_id_bytes)))
    parts.append(request_id_bytes)

    # is_final_token
    parts.append(struct.pack('!?', response_dict['is_final_token']))

    # Error (if any)
    error = response_dict.get('error')
    if error is None:
        parts.append(struct.pack('!I', 0))
    else:
        error_bytes = error.encode('utf-8')
        parts.append(struct.pack('!I', len(error_bytes)))
        parts.append(error_bytes)

    # Output tokens - handle nested list structure
    if output_tokens is None:
        parts.append(struct.pack('!I', 0))  # 0 sublists
    else:
        parts.append(struct.pack('!I', len(output_tokens)))  # Number of sublists
        for sublist in output_tokens:
            if sublist is None:
                parts.append(struct.pack('!I', 0))
            else:
                # Convert to numpy array for efficient serialization
                arr = np.array(sublist, dtype=np.int32)
                parts.append(struct.pack('!I', len(arr)))
                parts.append(arr.tobytes())

    return b''.join(parts)


def _np_deserialize_response(data):
    """
    Deserialize response data using numpy for integer lists.
    """
    offset = 0

    # Read header
    version, = struct.unpack_from('!B', data, offset)
    offset += 4

    if version != 1:
        raise ValueError(f"Unsupported protocol version: {version}")

    # Read request ID
    request_id_len, = struct.unpack_from('!I', data, offset)
    offset += 4
    request_id_str = data[offset:offset + request_id_len].decode('utf-8')
    offset += request_id_len

    # Convert back to int if it looks like an integer
    try:
        request_id = int(request_id_str)
    except ValueError:
        request_id = request_id_str

    # Read is_final_token
    is_final_token, = struct.unpack_from('!?', data, offset)
    offset += 1

    # Read error
    error_len, = struct.unpack_from('!I', data, offset)
    offset += 4
    error = None
    if error_len > 0:
        error = data[offset:offset + error_len].decode('utf-8')
        offset += error_len

    # Read output tokens
    num_sublists, = struct.unpack_from('!I', data, offset)
    offset += 4

    output_tokens = None
    if num_sublists > 0:
        output_tokens = []
        for _ in range(num_sublists):
            sublist_len, = struct.unpack_from('!I', data, offset)
            offset += 4
            if sublist_len > 0:
                # Use numpy to efficiently deserialize int32 array
                arr = np.frombuffer(data, dtype=np.int32, count=sublist_len, offset=offset)
                output_tokens.append(arr.tolist())
                offset += sublist_len * 4
            else:
                output_tokens.append([])

    return {
        'request_id': request_id,
        'output_tokens': output_tokens,
        'is_final_token': is_final_token,
        'error': error
    }


class AsyncLLMHttpRequestManager:
    """Asynchronous HTTP client for concurrent LLM request execution."""

    def __init__(self,
                 config: TrtllmEndpointConfig,
                 max_concurrency: int,
                 workers_per_core: int,
                 log_dir: str):
        self.config = config
        self.max_concurrency = max_concurrency
        self.workers_per_core = workers_per_core
        self.log_dir = log_dir
        self.model_name, self.model_revision = list(self.config.get_model_repo().items())[0]

        self._response_queue = None
        self._zmq_resources_initialized = False
        self._is_shutdown = False
        self._worker_manager = None
        self._response_poller = None  # Reusable poller for get_responses

        self._initialize()

    def _initialize(self):
        """Initialize multiprocess mode with ZMQ worker processes."""
        # Setup ZMQ endpoints - unique per AsyncHttpClient instance
        # shared by all workers processes of a TrtllmEndpointCore
        instance_id = str(uuid.uuid4())[:8]
        self.request_endpoint = f"ipc:///tmp/trtllm_zmq_requests_{instance_id}.ipc"
        self.response_endpoint = f"ipc:///tmp/trtllm_zmq_responses_{instance_id}.ipc"

        # Setup ZMQ context and sockets
        self.zmq_context = zmq.Context(io_threads=self.workers_per_core)

        # NOTE(vir):
        # HighWaterMark (HWM) is the size of the IPC queue (max num of pending message)
        # - independent of message-size (eg: ISL/OSL).
        # - SHOULD BE > max-num-requests (in offline) for 1 LLMCore (endpoint) across ALL scenarios / workloads

        # PUSH socket to send requests to workers (load-balanced automatically)
        self.request_socket = self.zmq_context.socket(zmq.PUSH)
        self.request_socket.bind(self.request_endpoint)
        self.request_socket.setsockopt(zmq.SNDHWM, 2_000_000)
        self.request_socket.setsockopt(zmq.LINGER, 0)

        # PULL socket to receive responses from workers
        self.response_socket = self.zmq_context.socket(zmq.PULL)
        self.response_socket.bind(self.response_endpoint)
        self.response_socket.setsockopt(zmq.RCVHWM, 2_000_000)

        # Create reusable poller for efficient response polling
        self._response_poller = zmq.Poller()
        self._response_poller.register(self.response_socket, zmq.POLLIN)

        self._zmq_resources_initialized = True

        # Create worker manager instance
        self._worker_manager = WorkerProcessManager()

        # Register ZMQ cleanup as a pre-cleanup callback
        # This ensures ZMQ shutdown signals are sent before processes are terminated
        def zmq_pre_cleanup():
            self._send_shutdown_signals()
            time.sleep(0.1)
            self._cleanup_resources()
        self._worker_manager.add_pre_cleanup_callback(zmq_pre_cleanup)

        # -1 means unlimited concurrency
        # otherwise, we divide max_concurrency by workers_per_core
        if self.max_concurrency == -1:
            worker_concurrency = -1
        else:
            worker_concurrency = self.max_concurrency // self.workers_per_core

        init_args = [
            self.config,
            worker_concurrency,
            self.request_endpoint,
            self.response_endpoint,
            self.model_name,
            self.model_revision
        ]

        # Start worker processes
        self.worker_processes = self._worker_manager.start_worker_processes(
            worker_count=self.workers_per_core,
            worker_main_func=self._worker_process_main,
            init_args=init_args,
            process_name_prefix="AsyncHttpEndpointWorker",
            log_dir=self.log_dir
        )

    def _cleanup_resources(self):
        """Clean up ZMQ resources (called by signal handlers)."""
        if not self._zmq_resources_initialized:
            return

        try:
            # Unregister socket from poller before closing
            if self._response_poller is not None:
                self._response_poller.unregister(self.response_socket)

            self.request_socket.close()
            self.response_socket.close()
            self.zmq_context.term()
        except Exception as e:
            logging.error(f"Error during ZMQ cleanup: {e}")
        finally:
            self._zmq_resources_initialized = False
            self._response_poller = None

    def _send_shutdown_signals(self):
        """Send shutdown signals to all worker processes."""
        if not self._zmq_resources_initialized:
            return

        try:
            # Send shutdown signal to all workers
            for _ in range(self.workers_per_core):
                self.request_socket.send(b'__SHUTDOWN__', zmq.DONTWAIT)
            logging.debug(f"Sent shutdown signals to {self.workers_per_core} workers")
        except Exception as e:
            logging.warning(f"Failed to send shutdown signals: {e}")

    def submit_requests(self, queries: List[LLMRequest]) -> None:
        """Submit requests in multiprocess mode using ZMQ PUSH socket."""
        # Don't submit new requests if we're shutting down
        if self._is_shutdown:
            return

        # Send each request individually for proper load balancing across workers
        for query in queries:
            request_data = _np_serialize_request({
                'request_id': query.request_id,
                'input_tokens': query.input_tokens,
                'stop_tokens': query.stop_tokens,
            })

            try:
                # Non-blocking send to IPC queue
                self.request_socket.send(request_data, zmq.DONTWAIT)
            except zmq.Again:
                raise RuntimeError("Request queue is full")

    def get_responses(self, timeout) -> List[LLMResponse]:
        """
        Get all available responses from the ZMQ socket within a timeout
        using a Poller for efficient waiting with minimal CPU usage.
        """
        if self._is_shutdown:
            return []

        responses = []

        try:
            # poll() waits for an event or times out. Timeout is in milliseconds.
            timeout_ms = timeout.total_seconds() * 1000 if timeout is not None else 0

            socks = dict(self._response_poller.poll(timeout_ms))

            # If the poller returns our socket, it means messages are ready
            if self.response_socket in socks:
                # Drain all messages currently in the queue in a non-blocking way
                while True:
                    try:
                        # Use copy=False to avoid an extra data copy, improving performance
                        response_data = self.response_socket.recv(zmq.DONTWAIT, copy=False)

                        # When using copy=False, a Frame object is returned; access with .bytes
                        response_dict = _np_deserialize_response(response_data.bytes)

                        responses.extend([LLMResponse(
                            request_id=response_dict['request_id'],
                            output_tokens=response_dict['output_tokens'],
                            is_final_token=response_dict['is_final_token'],
                            error=response_dict.get('error')
                        )])

                    except zmq.Again:
                        # zmq.Again means the queue is empty
                        break

        except zmq.ZMQError as e:
            if e.errno == zmq.ENOTSOCK:
                logging.info("ZMQ socket closed during response polling - shutting down gracefully")
            else:
                raise RuntimeError(f"ZMQ error while getting responses: {e}")
        except Exception as e:
            raise RuntimeError(f"Error while getting responses: {e}")

        return responses

    def shutdown(self):
        """Clean up resources based on execution mode."""
        if self._is_shutdown:
            return  # Already shut down

        self._is_shutdown = True

        # Send shutdown signal to all workers
        self._send_shutdown_signals()
        time.sleep(0.1)
        self._worker_manager.shutdown_workers(self.worker_processes, [])

        # Clean up ZMQ resources
        self._cleanup_resources()

    @classmethod
    def _worker_process_main(cls, config: TrtllmEndpointConfig, max_concurrency: int,
                             request_endpoint: str, response_endpoint: str,
                             model_name: str, model_revision: str,
                             worker_id: int, readiness_queue: mp.Queue,):
        """Main function for ZMQ multiprocess worker."""
        # NOTE(vir):
        # default is false, seems sufficient in my testing
        # can toggle here and capture nsys to measure any differences for very long OSL
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'

        loop = uvloop.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(cls._worker_loop(config, max_concurrency,
                                                     request_endpoint, response_endpoint,
                                                     readiness_queue, model_name, model_revision))
        finally:
            loop.close()

    @classmethod
    async def _worker_loop(cls, config: TrtllmEndpointConfig, max_concurrency: int,
                           request_endpoint: str, response_endpoint: str,
                           readiness_queue: mp.Queue, model_name: str, model_revision: str):
        """Worker loop for ZMQ multiprocess mode."""
        # Create ZMQ asyncio context for this worker
        zmq_context = zmq.asyncio.Context()

        # NOTE(vir):
        # HighWaterMark (HWM) is the size of the IPC queue (max num of pending message)
        # - independent of message-size (eg: ISL/OSL).
        # - SHOULD BE > max-num-requests (in offline) for 1 LLMCore (endpoint) across ALL scenarios / workloads

        # PULL socket to receive requests
        request_socket = zmq_context.socket(zmq.PULL)
        request_socket.connect(request_endpoint)
        request_socket.setsockopt(zmq.RCVHWM, 2_000_000)

        # PUSH socket to send responses
        response_socket = zmq_context.socket(zmq.PUSH)
        response_socket.connect(response_endpoint)
        response_socket.setsockopt(zmq.SNDHWM, 2_000_000)
        response_socket.setsockopt(zmq.LINGER, 0)

        try:
            request_provider = AsyncHttpLLMClient(config, max_concurrency, model_name, model_revision)
            await request_provider.initialize()
            readiness_queue.put(True)
        except Exception as e:
            readiness_queue.put(f"Worker initialization failed: {e}")
            zmq_context.term()
            return

        active_tasks = set()
        processed_queries = 0  # Track number of queries processed by this worker

        while True:
            try:
                # Asynchronously receive request
                request_data = await request_socket.recv()

                # Check for shutdown signal
                if request_data == b'__SHUTDOWN__':
                    logging.info(f"Worker (PID: {os.getpid()}) received shutdown signal")
                    break

                # Deserialize request
                request_dict = _np_deserialize_request(request_data)
                request = LLMRequest(
                    request_id=request_dict['request_id'],
                    input_tokens=request_dict['input_tokens'],
                    stop_tokens=request_dict['stop_tokens']
                )

                # Increment processed query counter
                processed_queries += 1

                # Launch request processing task
                task = asyncio.create_task(request_provider.process_request(request, response_socket))
                active_tasks.add(task)
                task.add_done_callback(active_tasks.discard)

            except Exception as e:
                raise RuntimeError(f"Worker encountered an error: {e}")

        # Wait for all active tasks to complete
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
            logging.info(f"Worker (PID: {os.getpid()}) completed all active tasks")

        # Log total queries processed by this worker
        logging.info(f"Worker process (PID: {os.getpid()}) processed {processed_queries} queries")

        await request_provider.shutdown()
        zmq_context.term()
        logging.info(f"Worker (PID: {os.getpid()}) shutdown complete")


class AsyncHttpLLMClient:
    """
    HTTP client for OpenAI LLM endpoints using aiohttp + orjson, ZMQ+msgpack for IPC.
    Supports multiprocess (ZMQ-based) mode for request concurrency.
    """

    def __init__(self, config: TrtllmEndpointConfig, max_concurrency: int, model_name: str, model_revision: str):
        self.config = config
        self.max_concurrency = max_concurrency
        self.model_name = model_name
        self.model_revision = model_revision
        self.endpoint_url = f"http://{config.endpoint_url}/v1/chat/completions"

        # Resources initialized in initialize()
        self.session: Optional[aiohttp.ClientSession] = None
        self.tokenizer: Optional[AutoTokenizer] = None
        self.concurrency_semaphore = None

    async def initialize(self):
        """Initialize HTTP session, tokenizer, and concurrency control."""
        # Create semaphore for concurrency control
        if self.max_concurrency == -1:
            self.concurrency_semaphore = None
            connection_limit = self.config.build_flags['max_batch_size'] * 2
        else:
            self.concurrency_semaphore = asyncio.Semaphore(self.max_concurrency)
            connection_limit = self.max_concurrency

        # aiohttp uses current event loop by default
        connector = aiohttp.TCPConnector(
            limit=0,
            limit_per_host=0,
            force_close=False,
            ssl=False,
        )

        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=None),
            json_serialize=orjson.dumps,
            headers={
                'Content-Type': 'application/json',
                'Authorization': 'Bearer dummy'
            }
        )

        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            revision=self.model_revision
        )

    async def process_request(self, request: LLMRequest, response_socket: zmq.asyncio.Socket) -> None:
        """Process request and send response via ZMQ (multiprocess mode)."""
        if self.concurrency_semaphore:
            async with self.concurrency_semaphore:
                await self._process_request_impl(request, response_socket)
        else:
            await self._process_request_impl(request, response_socket)

    async def _process_request_impl(self, request: LLMRequest, response_socket: zmq.asyncio.Socket) -> None:
        """Implementation of request processing for ZMQ mode."""
        payload = self._build_payload(request)

        try:
            if self.config.gen_config.streaming:
                await self._handle_streaming(request, payload, response_socket=response_socket)
            else:
                await self._handle_non_streaming(request, payload, response_socket=response_socket)
        except Exception as e:
            await self._send_response(LLMResponse(
                request_id=request.request_id,
                output_tokens=None,
                is_final_token=True,
                error=str(e)
            ), response_socket)

    def _build_payload(self, request: LLMRequest) -> bytes:
        """Build optimized request payload using orjson."""
        data = {
            "model": self.model_name,
            "messages": [],
            "max_tokens": self.config.gen_config.max_output_len,
            "temperature": self.config.gen_config.temperature,
            "top_p": self.config.gen_config.top_p,
            "stream": self.config.gen_config.streaming,
            "prompt_token_ids": request.input_tokens,
            "min_tokens": self.config.gen_config.min_output_len,
            "top_k": self.config.gen_config.top_k,
            # "detokenize": True,  # TODO(vir): disable detokenize
        }

        if self.config.gen_config.use_stop_tokens:
            data["stop_token_ids"] = request.stop_tokens

        return orjson.dumps(data)

    async def _handle_streaming(self, request: LLMRequest, payload: bytes,
                                response_queue=None, response_socket=None) -> None:
        """Handle streaming response with optimized chunk processing."""
        output_chunks = []
        first_token_sent = False
        first_token_length = 0
        buffer = bytearray(64 * 1024)
        processed_offset = 0
        is_final = False

        async with self.session.post(
            self.endpoint_url,
            data=payload,
        ) as response:
            response.raise_for_status()

            # Process SSE stream
            async for chunk in response.content.iter_any():
                buffer.extend(chunk)

                while True:
                    line_end = buffer.find(b'\n', processed_offset)
                    if line_end == -1:
                        break  # No more complete lines

                    line = buffer[processed_offset:line_end]
                    processed_offset = line_end + 1  # Move offset past the newline

                    if not line or line == b'data: [DONE]':
                        continue

                    if not line.startswith(b'data: '):
                        continue

                    try:
                        # Parse JSON directly from bytes
                        chunk_data = orjson.loads(line[6:])
                        choice = chunk_data.get('choices', [{}])[0]
                        delta = choice.get('delta', {})
                        content = delta.get('content')
                        is_final = choice.get('finish_reason') is not None

                        if content:
                            output_chunks.append(content)

                            # Send first token immediately
                            if not first_token_sent:
                                first_token_sent = True
                                first_tokens = self.tokenizer.encode(content).ids
                                first_token_length = len(first_tokens)

                                first_response = LLMResponse(
                                    request_id=request.request_id,
                                    output_tokens=[first_tokens],
                                    is_final_token=is_final,
                                    error=None
                                )

                                if response_queue is not None:
                                    response_queue.put(first_response)
                                elif response_socket is not None:
                                    await self._send_response(first_response, response_socket)

                        # Check for completion - exit early when finish_reason is present
                        if is_final:
                            break

                    except Exception as e:
                        # Skip malformed chunks
                        continue

                # If finish_reason was found, break from the outer chunk-processing loop
                if is_final:
                    break

                # After the loop, compact the buffer by removing the processed part
                if processed_offset > 0:
                    del buffer[:processed_offset]
                    processed_offset = 0

        # Send final response with remaining tokens
        if output_chunks:
            full_text = ''.join(output_chunks)
            all_tokens = self.tokenizer.encode(full_text).ids
            remaining_tokens = all_tokens[first_token_length:] if first_token_sent else all_tokens
        else:
            remaining_tokens = []

        final_response = LLMResponse(
            request_id=request.request_id,
            output_tokens=[remaining_tokens],
            is_final_token=True,
            error=None
        )

        if response_queue is not None:
            response_queue.put(final_response)
        elif response_socket is not None:
            await self._send_response(final_response, response_socket)

    async def _handle_non_streaming(self, request: LLMRequest, payload: bytes,
                                    response_queue=None, response_socket=None) -> None:
        """Handle non-streaming response."""
        async with self.session.post(
            self.endpoint_url,
            data=payload,
        ) as response:
            response.raise_for_status()
            data = await response.read()
            result = orjson.loads(data)

            content = result['choices'][0]['message']['content']
            output_tokens = self.tokenizer.encode(content).ids

            response_obj = LLMResponse(
                request_id=request.request_id,
                output_tokens=[output_tokens],
                is_final_token=True,
                error=None
            )

            if response_queue is not None:
                response_queue.put(response_obj)
            elif response_socket is not None:
                await self._send_response(response_obj, response_socket)

    async def _send_response(self, response: LLMResponse, response_socket: zmq.asyncio.Socket) -> None:
        """Send response via ZMQ socket."""
        response_data = _np_serialize_response({
            'request_id': response.request_id,
            'output_tokens': response.output_tokens,
            'is_final_token': response.is_final_token,
            'error': response.error
        })

        await response_socket.send(response_data)

    async def shutdown(self):
        """Clean up resources."""
        if self.session:
            await self.session.close()
