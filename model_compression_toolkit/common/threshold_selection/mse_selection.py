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

import numpy as np

from model_compression_toolkit.common.constants import MIN_THRESHOLD, THRESHOLD
from model_compression_toolkit.common.threshold_selection.threshold_search import \
    threshold_selection_tensor_search, threshold_selection_histogram_search


def mse_error_function(x: np.ndarray,
                       y: np.ndarray,
                       threshold: float) -> np.float:
    """
    Compute the mean square error between two tensors x and y.

    Args:
        threshold: Threshold the quantized tensor was quantized by.
        x: Fake-quantized tensor of y.
        y: Float tensor.

    Returns:
        The mean square error between the two tensors.
    """

    return np.power(x - y, 2.0).mean()


def mse_error_histogram(q_bins: np.ndarray,
                        q_count: np.ndarray,
                        bins: np.ndarray,
                        counts: np.ndarray) -> np.float:
    """
    Compute the error function between a histogram to its quantized version.
    The error is computed based on the mean square error the distributions have.

    Args:
        q_bins: Bins values of the quantized histogram.
        q_count: Bins counts of the quantized histogram.
        bins: Bins values of the original histogram.
        counts: Bins counts of the original histogram.

    Returns:
        MSE between the two histograms.
    """

    return np.sum((np.power((q_bins - bins)[:-1], 2.0) * counts)) / np.sum(counts)


def mse_selection_tensor(tensor_data: np.ndarray,
                         p: int,
                         n_bits: int,
                         per_channel: bool = False,
                         channel_axis: int = 1,
                         n_iter: int = 10,
                         min_threshold: float = MIN_THRESHOLD) -> dict:
    """
    Compute the optimal threshold based on mean square error (MSE) to quantize the tensor.
    The threshold is constrained and the search is done iteratively over n_iter thresholds.
    A minimal threshold to choose when the computed threshold is smaller can be passed.

    Args:
        tensor_data: Tensor content as Numpy array.
        p: p-norm to use for the Lp-norm distance (not used for this method).
        n_bits: Number of bits to quantize the tensor.
        per_channel: Whether the quantization should be per-channel or not.
        channel_axis: Output channel index.
        n_iter: Number of iterations to search for the optimal threshold.
        min_threshold: Minimal threshold to chose when the computed one is smaller.

    Returns:
        Optimal threshold to quantize the tensor based on MSE.
    """

    return {THRESHOLD: threshold_selection_tensor_search(mse_error_function,
                                                         tensor_data,
                                                         n_bits,
                                                         per_channel=per_channel,
                                                         channel_axis=channel_axis,
                                                         n_iter=n_iter,
                                                         min_threshold=min_threshold)}


def mse_selection_histogram(bins: np.ndarray,
                            counts: np.ndarray,
                            p: int,
                            n_bits: int,
                            min_value: float,
                            max_value: float,
                            constrained: bool = True,
                            n_iter: int = 10,
                            min_threshold: float = MIN_THRESHOLD) -> dict:
    """
    Compute the optimal threshold based on the mean square error (MAE) to quantize a histogram.
    The threshold is either constrained or unconstrained and the search is done iteratively over
    n_iter thresholds. Minimal threshold to use if threshold is too small can be passed.

    Args:
        bins: Bins values of the histogram.
        counts: Bins counts of the histogram.
        p: p-norm to use for the Lp-norm distance (not used for this method).
        n_bits: Number of bits to quantize the tensor.
        min_value: Min value (not used for this method).
        max_value: Max value (not used for this method).
        constrained: Whether the threshold should be constrained or not.
        n_iter: Number of iteration ot search for the threshold.
        min_threshold: Minimal threshold to use if threshold is too small.

    Returns:
        Optimal threshold to quantize the histogram based on the MSE.
    """
    return {THRESHOLD: threshold_selection_histogram_search(mse_error_histogram,
                                                            bins,
                                                            counts,
                                                            n_bits,
                                                            constrained=constrained,
                                                            n_iter=n_iter,
                                                            min_threshold=min_threshold)}
