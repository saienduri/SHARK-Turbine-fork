# Copyright 2023 Nod Labs, Inc
#
# Licensed under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import os
import sys

from iree import runtime as ireert
import iree.compiler as ireec
from iree.compiler.ir import Context
import numpy as np
from shark_turbine.aot import *
from turbine_models.custom_models.sd_inference import utils
import torch
import torch._dynamo as dynamo
from transformers import CLIPTextModel, CLIPTokenizer
from turbine_models.turbine_tank import turbine_tank

import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--hf_auth_token", type=str, help="The Hugging Face auth token, required"
)
parser.add_argument(
    "--hf_model_name",
    type=str,
    help="HF model name",
    default="CompVis/stable-diffusion-v1-4",
)
parser.add_argument("--compile_to", type=str, help="torch, linalg, vmfb")
parser.add_argument("--external_weight_path", type=str, default="")
parser.add_argument(
    "--external_weights",
    type=str,
    default=None,
    help="saves ir/vmfb without global weights for size and readability, options [safetensors]",
)
parser.add_argument("--device", type=str, default="cpu", help="cpu, cuda, vulkan, rocm")
# TODO: Bring in detection for target triple
parser.add_argument(
    "--iree_target_triple",
    type=str,
    default="",
    help="Specify vulkan target triple or rocm/cuda target device.",
)
parser.add_argument("--vulkan_max_allocation", type=str, default="4294967296")
parser.add_argument(
    "--download_ir",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="download IR from turbine tank",
)
parser.add_argument(
    "--upload_ir",
    action=argparse.BooleanOptionalAction,
    default=False,
    help="upload IR to turbine tank",
)


def export_clip_model(
    hf_model_name,
    hf_auth_token=None,
    compile_to="torch",
    external_weights=None,
    external_weight_path=None,
    device=None,
    target_triple=None,
    max_alloc=None,
    download_ir=False,
    upload_ir=False,
):
    # Load the tokenizer and text encoder to tokenize and encode the text.
    tokenizer = CLIPTokenizer.from_pretrained(
        hf_model_name,
        subfolder="tokenizer",
        token=hf_auth_token,
    )

    if download_ir:
        return turbine_tank.downloadModelArtifacts(hf_model_name + "-clip"), tokenizer

    text_encoder_model = CLIPTextModel.from_pretrained(
        hf_model_name,
        subfolder="text_encoder",
        token=hf_auth_token,
    )

    mapper = {}
    utils.save_external_weights(
        mapper, text_encoder_model, external_weights, external_weight_path
    )

    class CompiledClip(CompiledModule):
        if external_weights:
            params = export_parameters(
                text_encoder_model,
                external=True,
                external_scope="",
                name_mapper=mapper.get,
            )
        else:
            params = export_parameters(text_encoder_model)

        def main(self, inp=AbstractTensor(1, 77, dtype=torch.int64)):
            return jittable(text_encoder_model.forward)(inp)

    import_to = "INPUT" if compile_to == "linalg" else "IMPORT"
    inst = CompiledClip(context=Context(), import_to=import_to)

    module_str = str(CompiledModule.get_mlir_module(inst))
    safe_name = utils.create_safe_name(hf_model_name, "-clip")
    if upload_ir:
        with open(f"{safe_name}.mlir", "w+") as f:
            f.write(module_str)
        model_name_upload = hf_model_name.replace("/", "_")
        model_name_upload += "-clip"
        turbine_tank.uploadToBlobStorage(
            str(os.path.abspath(f"{safe_name}.mlir")),
            f"{model_name_upload}/{model_name_upload}.mlir",
        )
    if compile_to != "vmfb":
        return module_str, tokenizer
    else:
        utils.compile_to_vmfb(module_str, device, target_triple, max_alloc, safe_name)


if __name__ == "__main__":
    args = parser.parse_args()
    if args.upload_ir and args.download_ir:
        raise ValueError("upload_ir and download_ir can't both be true")
    mod_str, _ = export_clip_model(
        args.hf_model_name,
        args.hf_auth_token,
        args.compile_to,
        args.external_weights,
        args.external_weight_path,
        args.device,
        args.iree_target_triple,
        args.vulkan_max_allocation,
        args.download_ir,
        args.upload_ir,
    )
    safe_name = args.hf_model_name.split("/")[-1].strip()
    safe_name = re.sub("-", "_", safe_name)
    with open(f"{safe_name}.mlir", "w+") as f:
        f.write(mod_str)
    print("Saved to", safe_name + ".mlir")
