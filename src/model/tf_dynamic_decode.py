# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
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
"""Seq2seq layer operations for use in neural networks."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import six

from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import tensor_shape
from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import rnn
from tensorflow.python.ops import tensor_array_ops
from tensorflow.python.ops import variable_scope
from tensorflow.python.util import nest
from tensorflow.contrib.seq2seq import Decoder
import tf_commons as tfc
import data_commons as dtc

__all__ = ["dynamic_decode"]


_transpose_batch_time = rnn._transpose_batch_time  # pylint: disable=protected-access





def _create_zero_outputs(size, dtype, batch_size):
  """Create a zero outputs Tensor structure."""
  def _t(s):
    return (s if isinstance(s, ops.Tensor) else constant_op.constant(
        tensor_shape.TensorShape(s).as_list(),
        dtype=dtypes.int32,
        name="zero_suffix_shape"))

  def _create(s, d):
    return array_ops.zeros(
        array_ops.concat(
            ([batch_size], _t(s)), axis=0), dtype=d)

  return nest.map_structure(_create, size, dtype)


def dynamic_decode(decoder,
                   output_time_major=False,
                   impute_finished=False,
                   maximum_iterations=None,
                   parallel_iterations=32,
                   swap_memory=False,
                   scope=None):
  """Perform dynamic decoding with `decoder`.

  Calls initialize() once and step() repeatedly on the Decoder object.

  Args:
    decoder: A `Decoder` instance.
    output_time_major: Python boolean.  Default: `False` (batch major).  If
      `True`, outputs are returned as time major tensors (this mode is faster).
      Otherwise, outputs are returned as batch major tensors (this adds extra
      time to the computation).
    impute_finished: Python boolean.  If `True`, then states for batch
      entries which are marked as finished get copied through and the
      corresponding outputs get zeroed out.  This causes some slowdown at
      each time step, but ensures that the final state and outputs have
      the correct values and that backprop ignores time steps that were
      marked as finished.
    maximum_iterations: `int32` scalar, maximum allowed number of decoding
       steps.  Default is `None` (decode until the decoder is fully done).
    parallel_iterations: Argument passed to `tf.while_loop`.
    swap_memory: Argument passed to `tf.while_loop`.
    scope: Optional variable scope to use.

  Returns:
    `(final_outputs, final_state, final_sequence_lengths)`.

  Raises:
    TypeError: if `decoder` is not an instance of `Decoder`.
    ValueError: if `maximum_iterations` is provided but is not a scalar.
  """
  if not isinstance(decoder, Decoder):
    raise TypeError("Expected decoder to be type Decoder, but saw: %s" %
                    type(decoder))

  with variable_scope.variable_scope(scope, "decoder") as varscope:
    # Properly cache variable values inside the while_loop
    if varscope.caching_device is None:
      varscope.set_caching_device(lambda op: op.device)

    if maximum_iterations is not None:
      maximum_iterations = ops.convert_to_tensor(
          maximum_iterations, dtype=dtypes.int32, name="maximum_iterations")
      if maximum_iterations.get_shape().ndims != 0:
        raise ValueError("maximum_iterations must be a scalar")

    initial_finished, initial_inputs, initial_state = decoder.initialize()

    zero_outputs = _create_zero_outputs(decoder.output_size,
                                        decoder.output_dtype,
                                        decoder.batch_size)

    if maximum_iterations is not None:
      initial_finished = math_ops.logical_or(
          initial_finished, 0 >= maximum_iterations)
    initial_sequence_lengths = array_ops.zeros_like(
        initial_finished, dtype=dtypes.int32)
    initial_time = constant_op.constant(0, dtype=dtypes.int32)

    def _shape(batch_size, from_shape):
      if not isinstance(from_shape, tensor_shape.TensorShape):
        return tensor_shape.TensorShape(None)
      else:
        batch_size = tensor_util.constant_value(
            ops.convert_to_tensor(
                batch_size, name="batch_size"))
        return tensor_shape.TensorShape([batch_size]).concatenate(from_shape)

    def _create_ta(s, d):
      return tensor_array_ops.TensorArray(
          dtype=d,
          size=0,
          dynamic_size=True,
          element_shape=_shape(decoder.batch_size, s))

    def _create_states_ta(t):
      return tensor_array_ops.TensorArray(
          dtype=t.dtype,
          size=0,
          dynamic_size=True,
          clear_after_read=True,
          element_shape=t.shape
        )

    initial_outputs_ta = nest.map_structure(_create_ta, decoder.output_size,
                                            decoder.output_dtype)
    # dtc.logger.info('decoder.initial_state.shape=%s', tfc.nested_tf_shape(initial_state))
    initial_states_ta = nest.map_structure(_create_states_ta, initial_state)
    # dtc.logger.info('initial_states_ta=%s', initial_states_ta)

    def condition(unused_time, unused_outputs_ta, unused_state, unused_inputs,
                  finished, unused_sequence_lengths, unused_states_ta):
      return math_ops.logical_not(math_ops.reduce_all(finished))

    def body(time, outputs_ta, state, inputs, finished, sequence_lengths, states_ta):
      """Internal while_loop body.

      Args:
        time: scalar int32 tensor.
        outputs_ta: structure of TensorArray.
        state: (structure of) state tensors and TensorArrays.
        inputs: (structure of) input tensors.
        finished: bool tensor (keeping track of what's finished).
        sequence_lengths: int32 tensor (keeping track of time of finish).
        states_ta: structure of TensorArray for storing states.

      Returns:
        `(time + 1, outputs_ta, next_state, next_inputs, next_finished,
          next_sequence_lengths, states_ta)`.
        ```
      """
      (next_outputs, decoder_state, next_inputs,
       decoder_finished) = decoder.step(time, inputs, state)
      next_finished = math_ops.logical_or(decoder_finished, finished)
      if maximum_iterations is not None:
        next_finished = math_ops.logical_or(
            next_finished, time + 1 >= maximum_iterations)
      next_sequence_lengths = array_ops.where(
          math_ops.logical_and(math_ops.logical_not(finished), next_finished),
          array_ops.fill(array_ops.shape(sequence_lengths), time + 1),
          sequence_lengths)

      nest.assert_same_structure(state, decoder_state)
      nest.assert_same_structure(states_ta, decoder_state)
      nest.assert_same_structure(outputs_ta, next_outputs)
      nest.assert_same_structure(inputs, next_inputs)

      # Zero out output values past finish
      if impute_finished:
        emit = nest.map_structure(
            lambda out, zero: array_ops.where(finished, zero, out),
            next_outputs,
            zero_outputs)
      else:
        emit = next_outputs

      # Copy through states past finish
      def _maybe_copy_state(new, cur):
        # TensorArrays and scalar states get passed through.
        if isinstance(cur, tensor_array_ops.TensorArray):
          pass_through = True
        else:
          new.set_shape(cur.shape)
          pass_through = (new.shape.ndims == 0)
        return new if pass_through else array_ops.where(finished, cur, new)

      if impute_finished:
        next_state = nest.map_structure(
            _maybe_copy_state, decoder_state, state)
      else:
        next_state = decoder_state

      outputs_ta = nest.map_structure(lambda ta, out: ta.write(time, out),
                                      outputs_ta, emit)
      states_ta = nest.map_structure(lambda ta, st: ta.write(time, st),
                                      states_ta, next_state)

      return (time + 1, outputs_ta, next_state, next_inputs, next_finished,
              next_sequence_lengths, states_ta)

    res = control_flow_ops.while_loop(
        condition,
        body,
        loop_vars=[
            initial_time, initial_outputs_ta, initial_state, initial_inputs,
            initial_finished, initial_sequence_lengths, initial_states_ta
        ],
        parallel_iterations=parallel_iterations,
        swap_memory=swap_memory)

    final_outputs_ta = res[1]
    final_state = res[2]
    final_sequence_lengths = res[5]
    final_states_ta = res[6]

    final_outputs = nest.map_structure(lambda ta: ta.stack(), final_outputs_ta)
    final_states = nest.map_structure(lambda ta: ta.stack(), final_states_ta)

    try:
      final_outputs, final_state = decoder.finalize(
          final_outputs, final_state, final_sequence_lengths)
    except NotImplementedError:
      pass

    if not output_time_major:
      final_outputs = nest.map_structure(_transpose_batch_time, final_outputs)
      final_states = nest.map_structure(_transpose_batch_time, final_states)

  return final_outputs, final_state, final_sequence_lengths, final_states
