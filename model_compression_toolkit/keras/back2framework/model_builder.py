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


from enum import Enum

import tensorflow as tf
from tensorflow.python.keras.engine.base_layer import TensorFlowOpLayer
from tensorflow.python.keras.layers import Layer
from tensorflow.python.keras.layers.core import TFOpLambda
from tensorflow_model_optimization.python.core.quantization.keras.quantize_wrapper import QuantizeWrapper
from typing import Tuple, Any, Dict, List
from tensorflow.python.util.object_identity import Reference as TFReference


from model_compression_toolkit import common
from model_compression_toolkit import keras
from model_compression_toolkit.common import Node, Graph
from model_compression_toolkit.common.graph.edge import EDGE_SINK_INDEX
from model_compression_toolkit.keras.back2framework.instance_builder import OperationHandler
from model_compression_toolkit.keras.graph_substitutions.substituter import pre_build_substitute
from model_compression_toolkit.keras.reader.connectivity_handler import OutTensor

# In tf2.3 fake quant node is implemented as TensorFlowOpLayer, while in tf2.4 as TFOpLambda.
FQ_NODE_OP_V2_3 = 'FakeQuantWithMinMaxVars'
FQ_NODE_OP_V2_4 = 'quantization.fake_quant_with_min_max_vars'
BATCH_INPUT_SHAPE = 'batch_input_shape'


class ModelBuilderMode(Enum):
    """
    Mode for building the model back from a graph:
    FLOAT - Build model for statistics collection. Model's outputs list contain all output tensors of all nodes
    in the graph.
    QUANTIZED - Build a quantized model using the nodes' quantization attributes for adding 
    quantization nodes to the model.
    KNOWLEDGEDISTILLATION - Build a quantized model using the nodes' quantization attributes for wrapping
    layers with QuantizeWrapper and output comparing points.
    """
    FLOAT = 0
    QUANTIZED = 1
    KNOWLEDGEDISTILLATION = 2


def get_node_name_from_layer(layer: Layer) -> str:
    """
    Get a node's name from the layer it was built from. For TensorFlowOpLayer
    we remove the prefix "tf_op_layer".

    Args:
        layer: Keras Layer to get its corresponding node's name.

    Returns:
        Name of the node that was built from the passed layer.
    """

    name = layer.name
    if isinstance(layer, TensorFlowOpLayer):  # remove TF op layer prefix
        name = '_'.join(name.split('_')[3:])
    return name


def is_layer_fake_quant(layer: Layer) -> bool:
    """
    Check whether a Keras layer is a fake quantization layer or not.
    Args:
        layer: Layer to check if it's a fake quantization layer or not.

    Returns:
        Whether a Keras layer is a fake quantization layer or not.
    """
    # in tf2.3 fake quant node is implemented as TensorFlowOpLayer, while in tf2.4 as TFOpLambda
    return (isinstance(layer, TensorFlowOpLayer) and layer.node_def.op == FQ_NODE_OP_V2_3) or (
            isinstance(layer, TFOpLambda) and layer.symbol == FQ_NODE_OP_V2_4)


def build_input_tensors_list(node: Node,
                             graph: Graph,
                             node_to_output_tensors_dict: Dict[Node, List[TFReference]]) -> List[List[TFReference]]:
    """
    Given a node, build a list of input tensors the node gets. The list is built
    based on the node's incoming edges and previous nodes' output tensors.

    Args:
        node: Node to build its input tensors list.
        graph: Graph the node is in.
        node_to_output_tensors_dict: A dictionary from a node to its output tensors.

    Returns:
        A list of the node's input tensors.
    """

    input_tensors = []
    # Go over a sorted list of the node's incoming edges, and for each source node get its output tensors.
    # Append them in a result list.
    for ie in graph.incoming_edges(node, sort_by_attr=EDGE_SINK_INDEX):
        _input_tensors = [node_to_output_tensors_dict[ie.source_node][ie.source_index]]
        input_tensors.append(_input_tensors)
    return input_tensors


def run_operation(n: Node,
                  input_tensors: List[List[TFReference]],
                  op_func: Layer,
                  input_nodes_to_input_tensors: Dict[Node, Any],
                  quantized: bool = True) -> List[TFReference]:
    """
    Applying the layer (op_func) to the input tensors (input_tensors).
    If quantized is set to True, and the layer's corresponding node (n) has quantization
    attributes, an additional fake-quantization node is built and appended to the layer.

    Args:
        n: The corresponding node of the layer it runs.
        input_tensors: List of references to Keras tensors that are the layer's inputs.
        op_func: Layer to apply to the input tensors.
        input_nodes_to_input_tensors: A dictionary from an node to its input tensors.

    Returns:
        A list of references to Keras tensors. The layer's output tensors after applying the
        layer to the input tensors.
    """

    if len(input_tensors) == 0:  # Placeholder handling
        out_tensors_of_n = input_nodes_to_input_tensors[n]
        if quantized:  # Add a fake quant node
            assert n.activation_quantization_cfg is not None  # Input layers should always have activation config
            fake_quant = n.activation_quantization_cfg.activation_quantization_fn(n.activation_quantization_cfg.activation_n_bits,
                                                                       n.activation_quantization_cfg.activation_is_signed,
                                                                       n.activation_quantization_cfg.activation_quantization_params)
            if fake_quant is not None:
                out_tensors_of_n = fake_quant(out_tensors_of_n)
            
    else:
        input_tensors = [tensor for tensor_list in input_tensors for tensor in tensor_list]  # flat list of lists
        
        # If operator expects a single input tensor, it cannot be a list as it should
        # have a dtype field.
        if len(input_tensors) == 1:
            out_tensors_of_n = op_func(input_tensors[0], **n.op_call_args)
        else:
            out_tensors_of_n = op_func(input_tensors, **n.op_call_args)

        # Add a fake quant node if the node has an activation threshold.
        if n.activation_quantization_cfg is not None:
            if quantized and n.activation_quantization_cfg.enable_activation_quantization:
                fake_quant = n.activation_quantization_cfg.activation_quantization_fn(n.activation_quantization_cfg.activation_n_bits,
                                                                           n.activation_quantization_cfg.activation_is_signed,
                                                                           n.activation_quantization_cfg.activation_quantization_params)
                if fake_quant is not None:
                    out_tensors_of_n = fake_quant(out_tensors_of_n)

    return out_tensors_of_n


def model_builder(graph: common.Graph,
                  mode: ModelBuilderMode = ModelBuilderMode.QUANTIZED,
                  append2output=None) -> Tuple[Any, Any]:
    """
    Build a Keras model from a graph representing the model.
    The model is built by converting the graph nodes to Keras layers and applying them sequentially to get the model
    output tensors. The output tensors list and an input tensors list, then use to build the model.
    When the model is not built in float mode, the graph is being transformed by additional substitutions.

    Args:
        graph: Graph to build its corresponding Keras model.
        mode: Building mode. Read ModelBuilderMode description for more info.
        append2output: List of nodes or OutTensor objects. In float building mode,
        when the list contains nodes, all output tensors of all nodes are set as the model outputs.

    Returns:
        A tuple of the model, and an UserInformation object.
    """

    # For quantized models, first apply some substitutions.
    if mode != ModelBuilderMode.FLOAT:
        graph = pre_build_substitute(graph)

    node_to_output_tensors_dict = dict()
    model_output_tensors = []

    # Build an OperationHandler to handle conversions from graph nodes to Keras operators.
    oh = OperationHandler(graph)

    # Create a list of output nodes with their tensors' indices that are model's output. When building
    # in float mode, if a node has multiple out tensors, the node should appear in append2output multiple
    # times, thus creating OutTensor for each output tensor.
    if append2output is not None:
        output_list = [OutTensor(n, 0) for n in append2output]
    else:
        output_list = graph.get_outputs()

    # Hold a dictionary from an input node to its corresponding input tensor. It is needed for when
    # building the model. Initially input nodes with input tensors are added to the dictionary,
    # as they're not added later.
    input_nodes_to_input_tensors = {inode: tf.keras.layers.Input(inode.framework_attr[BATCH_INPUT_SHAPE][1:]) for
                                    inode in graph.get_inputs()}

    # Build a list of the model's input tensors. Switching from a dictionary to a list
    # to keep the tensors input order, since inputs in Graph are ordered by their indices.
    inputs_list = []
    for input_node in graph.get_inputs():
        inputs_list.append(input_nodes_to_input_tensors.get(input_node))

    # Build a dictionary from node to its output tensors, by applying the layers sequentially.
    for n in oh.node_sort:
        op_func = oh.get_node_op_function(n)  # Get node operation function
        input_tensors = build_input_tensors_list(n,
                                                 graph,
                                                 node_to_output_tensors_dict)  # Fetch Node inputs
        out_tensors_of_n = run_operation(n,  # Run node operation and fetch outputs
                                         input_tensors,
                                         op_func,
                                         input_nodes_to_input_tensors,
                                         quantized=mode == ModelBuilderMode.QUANTIZED)

        if isinstance(out_tensors_of_n, list):
            node_to_output_tensors_dict.update({n: out_tensors_of_n})
        else:
            node_to_output_tensors_dict.update({n: [out_tensors_of_n]})

    # convert node_to_output_tensors_dict keys to nodes' names since oh.node_sort contains different objects than
    # original graph nodes.
    node_name_to_outtensors = dict()
    for node, tensors in node_to_output_tensors_dict.items():
        node_name_to_outtensors[node.name] = tensors

    for ot in output_list:
        if len(node_name_to_outtensors[ot.node.name]) == 1 or append2output is None:
            model_output_tensors.append(node_name_to_outtensors[ot.node.name][ot.node_out_index])
        else:  # When building float model - we collect all outputs from all nodes regardless the actual model's outputs
            model_output_tensors.append(node_name_to_outtensors[ot.node.name])

    # Build the model.
    model = tf.keras.Model(inputs=inputs_list, outputs=model_output_tensors)

    # In KNOWLEDGEDISTILLATION mode, wrap each layer in a QuantizeWrapper containing QuantizeConfig
    # that's built using the node quantization attributes.
    if mode == ModelBuilderMode.KNOWLEDGEDISTILLATION:
        def _quantize(layer):
            nodes = graph.find_node_by_name(get_node_name_from_layer(layer))
            if len(nodes) == 1:
                node = nodes[0]
                return QuantizeWrapper(layer, keras.quantizer.quantization_config_builder_kd(node))
            else:
                raise Exception(
                    f'Mismatch between keras model and graph cant find node named: {get_node_name_from_layer(layer)}')

        # clone each layer in the model and apply _quantize to the layer.
        model = tf.keras.models.clone_model(model, input_tensors=None, clone_function=_quantize)

    # Models that were built in float or quantized mode, should not be modified anymore.
    elif mode == ModelBuilderMode.FLOAT or mode == ModelBuilderMode.QUANTIZED:
        pass
    else:
        common.Logger.exception(f'Unknown model mode: {mode}')

    return model, graph.user_info
