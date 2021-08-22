# Copyright 2021 Sony Semiconductors Israel, Inc. All rights reserved.
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
# ==============================================================================


import tensorflow as tf
from tensorflow.python.keras.engine.functional import Functional
from tensorflow.python.keras.engine.node import Node as KerasNode
from tensorflow.python.keras.engine.sequential import Sequential

from model_compression_toolkit.common.graph.node import Node

keras = tf.keras
layers = keras.layers


def is_node_an_input_layer(node: Node) -> bool:
    """
    Checks if a node represents a Keras input layer.
    Args:
        node: Node to check if its an input layer.

    Returns:
        Whether the node represents an input layer or not.
    """
    if isinstance(node, Node):
        return node.layer_class == layers.InputLayer
    elif isinstance(node, KerasNode):
        return isinstance(node.layer, layers.InputLayer)
    else:
        raise Exception('Node to check has to be either a graph node or a keras node')


def is_node_a_model(node: Node) -> bool:
    """
    Checks if a node represents a Keras model.
    Args:
        node: Node to check if its a Keras model by itself.

    Returns:
        Whether the node represents a Keras model or not.
    """
    if isinstance(node, Node):
        return node.layer_class in [Functional, Sequential]
    elif isinstance(node, KerasNode):
        return isinstance(node.layer, Functional) or isinstance(node.layer, Sequential)
    else:
        raise Exception('Node to check has to be either a graph node or a keras node')

    # return node.layer_class in [Functional, Sequential]
