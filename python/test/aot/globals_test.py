# Copyright 2023 Nod Labs, Inc
#
# Licensed under the Apache License v2.0 with LLVM Exceptions.
# See https://llvm.org/LICENSE.txt for license information.
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception

import logging
import unittest

from iree.compiler.ir import (
    Context,
)

from shark_turbine.aot import *

import torch
import torch.nn as nn


class SimpleParams(nn.Module):
    def __init__(self):
        super().__init__()
        self.classifier = nn.Linear(20, 30)

    def forward(self, x):
        return self.classifier(x)


class ArgsTest(unittest.TestCase):
    def testGlobalParameters(self):
        m = SimpleParams()

        class GlobalModule(CompiledModule):
            params = export_parameters(m)
            compute = jittable(m.forward)

            def run(self, x=AbstractTensor(128, 20)):
                return self.compute(x)

        inst = GlobalModule(context=Context())
        module_str = str(CompiledModule.get_mlir_module(inst))
        print(module_str)
        self.assertIn("util.global private @_params.classifier.weight", module_str)
        self.assertIn("util.global private @_params.classifier.bias", module_str)

    def testGlobalLoadFromPyTree(self):
        m = SimpleParams()

        class GlobalModule(CompiledModule):
            params = export_parameters(m)

            def read_params(self):
                return self.params

        inst = GlobalModule(context=Context())
        module_str = str(CompiledModule.get_mlir_module(inst))
        print(module_str)
        self.assertIn(
            "%_params.classifier.weight = util.global.load @_params.classifier.weight",
            module_str,
        )
        self.assertIn(
            "%_params.classifier.bias = util.global.load @_params.classifier.bias",
            module_str,
        )
        self.assertIn(
            "return %_params.classifier.weight, %_params.classifier.bias", module_str
        )

    def testGlobalLoadFromPyLeaf(self):
        m = SimpleParams()

        class GlobalModule(CompiledModule):
            params = export_parameters(m)

            def read_weight(self):
                return self.params["classifier.weight"]

        inst = GlobalModule(context=Context())
        module_str = str(CompiledModule.get_mlir_module(inst))
        print(module_str)
        self.assertIn(
            "%_params.classifier.weight = util.global.load @_params.classifier.weight",
            module_str,
        )
        self.assertIn("return %_params.classifier.weight", module_str)

    def testGlobalStoreFromPyTree(self):
        m = SimpleParams()

        class GlobalModule(CompiledModule):
            params = export_parameters(m, initialize=False, mutable=True)

            def update_params(me, updates=abstractify(params)):
                self.assertIn("classifier.weight", updates)
                self.assertIn("classifier.bias", updates)
                me.params = updates

        inst = GlobalModule(context=Context())
        module_str = str(CompiledModule.get_mlir_module(inst))
        print(module_str)
        self.assertIn("util.global.store %arg0, @_params.classifier.weight", module_str)
        self.assertIn("util.global.store %arg1, @_params.classifier.bias", module_str)

    def testGlobalStoreFromLeaf(self):
        m = SimpleParams()

        class GlobalModule(CompiledModule):
            params = export_parameters(m, initialize=False, mutable=True)

            def update_bias(self, new_bias=abstractify(params["classifier.bias"])):
                self.params["classifier.bias"] = new_bias

        inst = GlobalModule(context=Context())
        module_str = str(CompiledModule.get_mlir_module(inst))
        print(module_str)
        self.assertIn("util.global.store %arg0, @_params.classifier.bias", module_str)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
