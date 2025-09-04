Tools
=====

Convert a Float32 Model to a BFloat16 Model  
-------------------------------------------  
  
Because of the increasing demands for BFloat16 deployment, a conversion tool is necessary to convert a Float32 model to a BFloat16 model. Four BFloat16 implementation formats are provided: **vitisqdq**, **with_cast**, **simulate_bf16**, and **bf16**.  
  
- **vitisqdq**: Implements BFloat16 conversion by inserting VitisQDQ of BFloat16.  
- **with_cast**: Implements BFloat16 conversion by inserting Cast operations to convert from Float32 to BFloat16.  
- **simulate_bf16**: Implements BFloat16 conversion by storing all BFloat16 weights in float format.  
- **bf16**: Implements BFloat16 conversion by directly converting the Float32 model to BFloat16, with only the input and output remaining as float.  
  
The default value is **with_cast**.  
  
Use the ``convert_fp32_to_bf16`` tool to convert a Float32 model to a BFloat16 model:  
  
.. code-block::

    python -m quark.onnx.tools.convert_fp32_to_bf16 --input $FLOAT_32_ONNX_MODEL_PATH --output $BFLOAT_16_ONNX_MODEL_PATH --format $BFLOAT_FORMAT

Convert a Float16 Model to a BFloat16 Model
-------------------------------------------

Because of increasing demands for BFloat16 deployment, a conversion tool is necessary to convert a Float16 model to a BFloat16 model. Four BFloat16 implementation formats are provided: **vitisqdq**, **with_cast**, **simulate_bf16**, and **bf16**.  
  
- **vitisqdq**: Implements BFloat16 conversion by inserting VitisQDQ of BFloat16.  
- **with_cast**: Implements BFloat16 conversion by inserting Cast operations to convert from Float16 to BFloat16.  
- **simulate_bf16**: Implements BFloat16 conversion by storing all BFloat16 weights in float format.  
- **bf16**: Implements BFloat16 conversion by directly converting the Float16 model to BFloat16, with only the input and output remaining as Float16.  
  
The default value is **with_cast**.  
  
Use the ``convert_fp16_to_bf16`` tool to convert a Float16 model to a BFloat16 model:  

.. code-block::

    python -m quark.onnx.tools.convert_fp16_to_bf16 --input $FLOAT_16_ONNX_MODEL_PATH --output $BFLOAT_16_ONNX_MODEL_PATH --format $BFLOAT_FORMAT

Convert a Float16 Model to a Float32 Model
------------------------------------------

Because the AMD Quark ONNX tool only supports Float32 models quantization currently, converting a model from Float16 to Float32 is required when quantizing a Float16 model.

Use the ``convert_fp16_to_fp32 tool`` to convert a Float16 model to a
Float32 model:

.. code-block::

    python -m pip install onnxsim
    python -m quark.onnx.tools.convert_fp16_to_fp32 --input $FLOAT_16_ONNX_MODEL_PATH --output $FLOAT_32_ONNX_MODEL_PATH


.. note::
    When using the ``convert_fp16_to_fp32`` tool in Quark ONNX, onnxsim is required to simplify the ONNX model. Ensure that onnxsim is installed by running ``python -m pip install onnxsim``

Convert a Float32 Model to a BFP16 Model
----------------------------------------

Since there are more and more BFP16 deployment demands, we need a conversion tool to directly convert a Float32 model to a BFP16 model.

Use the convert_fp32_to_bfp16 tool to convert a Float32 model to a BFP16 model:

.. code-block::

    python -m quark.onnx.tools.convert_fp32_to_bfp16 --input $FLOAT_32_ONNX_MODEL_PATH --output $BFP_16_ONNX_MODEL_PATH

Convert a Float16 Model to a BFP16 Model
------------------------------------------

Because there are more and more BFP16 deployment demands, we need a conversion tool to directly convert a Float16 model to a BFP16 model.

Use the convert_fp16_to_bfp16 tool to convert a Float16 model to a BFP16 model:

.. code-block::

    python -m quark.onnx.tools.convert_fp16_to_bfp16 --input $FLOAT_16_ONNX_MODEL_PATH --output $BFP_16_ONNX_MODEL_PATH

Convert a NCHW input Model to a NHWC Model
------------------------------------------

Given that some models are designed with an input shape of **NCHW** instead of **NHWC**, it is recommended to convert an NCHW input model to NHWC before quantizing a Float32 model. The conversion steps execute even if the model is already NHWC. Therefore, ensure the input model is in NCHW format.  
  
Use the ``convert_nchw_to_nhwc`` tool to convert an NCHW model to an NHWC model:  

.. code-block::

    python -m quark.onnx.tools.convert_nchw_to_nhwc --input $NCHW_ONNX_MODEL_PATH --output $NHWC_ONNX_MODEL_PATH

Quantize a ONNX Model Using Random Input
--------------------------------------

For some ONNX models without an input for quantization, use random input for the ONNX model quantization process.

Use the ``random_quantize`` tool to quantize an ONNX model:

.. code-block::

   python -m quark.onnx.tools.random_quantize --input_model $FLOAT_ONNX_MODEL_PATH --quant_model $QUANTIZED_ONNX_MODEL_PATH

Convert a A8W8 NPU Model to a A8W8 CPU Model
--------------------------------------------

Given that some models are quantized by A8W8 NPU, it is convenient and efficient to convert them to A8W8 CPU models.

Use the ``convert_a8w8_npu_to_a8w8_cpu`` tool to convert a A8W8 NPU model to a A8W8 CPU model:

.. code-block::

   python -m quark.onnx.tools.convert_a8w8_npu_to_a8w8_cpu --input [INPUT_PATH] --output [OUTPUT_PATH]

Print Names and Quantity of A16W8 and A8W8 Conv for Mixed-Precision Models
--------------------------------------------------------------------------

For some models that are mixed precision such as A18W8 and A8W8 mixed, use the ``print_a16w8_a8w8_nodes`` tool to print names and quantity of A16W8 and A8W8 Conv, ConvTranspose, Gemm, and MatMul. The MatMul node must have one and only one set of weights.

.. code-block::

   python -m quark.onnx.tools.print_a16w8_a8w8_nodes --input [INPUT_PATH]

Convert a U16U8 Quantized Model to a U8U8 Model
-----------------------------------------------

Convert a U16U8 (activations are quantized by UINT16 and weights by UINT8) to a U8U8 model without calibration.

Use the ``convert_u16u8_to_u8u8`` tool to do the conversion:

.. code-block::

    python -m quark.onnx.tools.convert_u16u8_to_u8u8 --input [INPUT_PATH] --output [OUTPUT_PATH]

Evaluate Accuracy Between Two Image Folders
-------------------------------------------

We often need to compare the differences in output images before and after quantization. Currently, we support four metrics: cosine similarity, L2 loss, PSNR, and VMAF, as well as three formats: JPG, PNG, and NPY.

Use the evaluate tool:

.. code-block::
    python -m quark.onnx.tools.evaluate.py --folder1 [IMAGE_FOLDER_1_PATH] --folder2 [IMAGE_FOLDER_2_PATH]

Replace `inf` and `-inf` Values in ONNX Model Weights
-----------------------------------------------------

Replace `inf` or `-inf` values in ONNX model weights using the ``replace_inf_weights`` tool with a specified value.

Use the ``replace_inf_weights`` tool to do the conversion:

.. code-block::

   python -m quark.onnx.tools.replace_inf_weights --input_model [INPUT_MODEL_PATH] --output_model [OUTPUT_MODEL_PATH] --replace_inf_value [REPLACE_INF_VALUE]

.. note::
   
    The default replacement value is `10000.0`. This might lead to precision degradation. Adjust the replacement value based on your model and application needs.
