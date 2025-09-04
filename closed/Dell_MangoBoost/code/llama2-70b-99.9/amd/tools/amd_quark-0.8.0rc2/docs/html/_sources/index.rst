.. AMD Quark documentation master file, created by
   sphinx-quickstart on Fri Mar 15 17:12:07 2024.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to AMD Quark Documentation!
===================================

**AMD Quark** is a comprehensive cross-platform deep learning toolkit designed to simplify and enhance the quantization
of deep learning models. Supporting both PyTorch and ONNX models, AMD Quark empowers developers to optimize their models for
deployment on a wide range of hardware backends, achieving significant performance gains without compromising accuracy.

.. figure:: _static/quark_stack.png
   :align: center
   :alt: Quark Stack

AMD Quark for PyTorch: Flexible and Efficient Quantization for PyTorch Models
-----------------------------------------------------------------------------

AMD Quark for PyTorch provides developers with a flexible, efficient, and easy-to-use toolkit for quantizing deep learning
models from PyTorch. The current quantization method is based on PyTorch in-place operator replacement.
In particular, the tool provides the key features and verified models as below:

Key Features
^^^^^^^^^^^^

* **Comprehensive Quantization Support**:
   - **Eager Mode Post-Training Quantization (PTQ):** Quantize pre-trained models without the need for retraining data.
   - **FX Graph Mode PTQ and Quantization-Aware Training (QAT):** Optimize models during training for superior accuracy on quantized hardware.
   - **Optimized QAT Methods:** Support Trained Quantization Thresholds For Accurate And Efficient Fixed-Point Inference Of Deep Neural Networks (TQT), Learned Step Size Quantization (LSQ) for better QAT result.
   - **Flexible Quantization Strategies:** Choose from symmetric/asymmetric, weight-only/static/dynamic quantization, and various quantization levels (per tensor/channel) to fine-tune performance and accuracy trade-offs.
   - **Extensive Data Type Support:** Quantize models using a wide range of data types, including `float16`, `bfloat16`, `int4`, `uint4`, `int8`, `fp8 (e4m3fn and e5m2)`, Shared Micro exponents with Multi-Level Scaling (`MX6`, `MX9`), and `Microscaling (MX)` data types with `int8`, `fp8_e4m3fn`, `fp8_e5m2`, `fp4`, `fp6_e3m2`, and `fp6_e2m3` elements.
   - **Configurable Calibration Methods:** Optimize quantization accuracy with `MinMax`, `Percentile`, and `MSE` calibration methods.
* **Advanced Capabilities:**
   - **Large Language Model Optimization:** Specialized support for quantizing large language models with `kv-cache` quantization.
   - **Cutting-Edge Algorithms:** Leverage state-of-the-art algorithms like `SmoothQuant`, `AWQ`, and `GPTQ` for `uint4` quantization on GPUs, achieving optimal performance for demanding tasks.
* **Seamless Integration and Deployment:**
   - **Export to multiple formats:** Export quantized models to `ONNX`, `JSON-safetensors`, and `GGUF` formats for deployment on a wide range of platforms.
   - **APL Integration:** Seamlessly integrate with AMD Pytorch-light (APL) for optimized performance on AMD hardware, to provide `INT-K`, `BFP16`, and `BRECQ` support.
   - **Experimental Brevitas Integration:** Explore seamless integration with Brevitas for quantizing Stable Diffusion and ImageNet classification models.
* **Examples included:** Benefit from practical examples for LLM models, SDXL models (Eager Mode), and CNN models (FX Graph Mode), accelerating your quantization journey.
* **Cross-Platform Support:** Develop and deploy on both Linux (CPU and GPU) and Windows (CPU mode) operating systems.

AMD Quark for ONNX: Streamlined Quantization for ONNX models
------------------------------------------------------------

AMD Quark for ONNX leverages the power of the ONNX Runtime Quantization tool,
providing a robust and flexible solution for quantizing ONNX models.

Key Features
^^^^^^^^^^^^

* **Comprehensive Quantization Support**:
   - **Post-Training Quantization (PTQ):** Quantize pre-trained models without the need for retraining data.
   - **Flexible Quantization Strategies:** Choose from symmetric/asymmetric, weight-only/static/dynamic quantization, and various quantization levels (per tensor/channel) to fine-tune performance and accuracy trade-offs.
   - **Extensive Data Type Support:** Quantize models using a wide range of data types, including `uint32`, `int32`, `float16`, `bfloat16`, `int16`, `uint16`, `int8`, `uint8`, Block Floating Point (typical `BFP16`), and `Microscaling (MX)` data types with `int8`, `fp8_e4m3fn`, `fp8_e5m2`, `fp4`, `fp6_e3m2`, and `fp6_e2m3` elements.
   - **Configurable Calibration Methods:** Optimize quantization accuracy with `MinMax`, `Entropy`, `Percentile`, `NonOverflow` and `MinMSE` calibration methods.
* **Advanced Capabilities:**
   - **Multiple Deployment Targets:** Target a variety of hardware platforms, including `NPU_CNN`, `NPU_Transformer`, and `CPU`.
   - **Cutting-Edge Algorithms:** Leverage state-of-the-art algorithms like `QuaRot`, `SmoothQuant`, `CLE`, `BiasCorrection`, `AdaQuant`, `AdaRound`, and `GPTQ` achieving optimal performance for demanding tasks.
   - **Flexible Scale Types:** Support quantization with `float scale`, `int16 scale`, and `power-of-two scale` options.
   - **Automatic Mixed Precision:**  Achieve an optimal balance between accuracy and performance through automatic mixed precision.

.. toctree::
   :hidden:
   :caption: Release Notes
   :maxdepth: 1

   Release Information <release_note.rst>

.. toctree::
   :hidden:
   :caption: Getting Started with AMD Quark
   :maxdepth: 1

   Introduction to Quantization <intro.rst>
   Installation <install.rst>
   Basic Usage <basic_usage.rst>
   Accessing PyTorch Examples <pytorch/pytorch_examples.rst>
   Accessing ONNX Examples <onnx/onnx_examples.rst>

.. _advanced-quark-features-pytorch:
.. toctree::
   :hidden:
   :caption: Advanced AMD Quark Features for PyTorch
   :maxdepth: 1

   Configuring PyTorch Quantization <pytorch/user_guide_config_description.rst>
   Save and Load Quantized Models <pytorch/quark_save_load>
   Exporting Quantized Models <pytorch/export/quark_export.rst>
   Best Practices for Post-Training Quantization (PTQ) <pytorch/quark_torch_best_practices.rst>
   Debugging quantization Degradation <pytorch/debug.rst>
   Language Model Optimization <pytorch/llm_quark.rst>
   Activation/Weight Smoothing (SmoothQuant) <pytorch/smoothquant.rst>
   Block Floating Point 16 <pytorch/tutorial_bfp16.rst>
   Extensions <pytorch/extensions.rst>
   Using MX (Microscaling) <pytorch/adv_mx.rst>
   Two Level Quantization Formats <pytorch/adv_two_level.rst>

.. _advanced-quark-features-onnx:
.. toctree::
   :hidden:
   :caption: Advanced Quark Features for ONNX
   :maxdepth: 1

   Configuring ONNX Quantization <onnx/user_guide_config_description.rst>
   Data and OP Types <onnx/user_guide_supported_optype_datatype.rst>
   Accelerate with GPUs <onnx/gpu_usage_guide.rst>
   Mixed Precision <onnx/tutorial_mix_precision.rst>
   Block Floating Point 16 (BFP16) <onnx/bfp16.rst>
   BF16 Quantization <onnx/tutorial_bf16_quantization.rst>
   Microscaling (MX) <onnx/tutorial_mx_quantization.rst>
   Accuracy Improvement Algorithms <onnx/accuracy_improvement_algorithms.rst>
   Optional Utilities <onnx/optional_utilities.rst>
   Tools <onnx/tools.rst>

.. toctree::
   :hidden:
   :caption: APIs
   :maxdepth: 1

   PyTorch APIs <pytorch/pytorch_apis.rst>
   ONNX APIs <onnx/onnx_apis.rst>

.. toctree::
   :hidden:
   :caption: Troubleshooting and Support
   :maxdepth: 1

   PyTorch FAQ <pytorch/pytorch_faq.rst>
   ONNX FAQ <onnx/onnx_faq.rst>
