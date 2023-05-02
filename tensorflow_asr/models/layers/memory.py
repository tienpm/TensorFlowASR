# Copyright 2023 Huy Le Nguyen (@usimarit)
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

import tensorflow as tf

from tensorflow_asr.models.base_layer import Layer
from tensorflow_asr.utils import math_util


class Memory(Layer):
    def __init__(self, batch_size, memory_length, dmodel, **kwargs):
        super().__init__(**kwargs)
        assert memory_length > 0, "memory_length must be integer"
        self.batch_size = batch_size
        self.memory_length = memory_length
        self.dmodel = dmodel
        self.stateful = True
        self.memory = self.add_weight(
            shape=(self.batch_size, self.memory_length, self.dmodel),
            initializer="zeros",
            trainable=False,
            dtype=self.dtype,
            name="memory",
        )
        self.memory_mask = self.add_weight(
            shape=(self.batch_size, self.memory_length),
            initializer="zeros",
            trainable=False,
            dtype=tf.bool,
            name="memory_mask",
        )

    def _prepend_memory_item(
        self,
        per_batch_memory,  # [M, D]
        per_batch_memory_mask,  # [M]
        per_batch_input,  # [T, D]
        per_batch_input_mask,  # [T]
        pad_right=True,
    ):
        memory_mask_count = math_util.count(per_batch_memory_mask, value=False)
        input_mask_count = math_util.count(per_batch_input_mask, value=False)

        # [M + T, D]
        per_batch_new_inputs = tf.concat([tf.stop_gradient(tf.roll(per_batch_memory, shift=memory_mask_count, axis=0)), per_batch_input], 0)
        per_batch_new_inputs_mask = tf.concat([tf.roll(per_batch_memory_mask, shift=memory_mask_count, axis=0), per_batch_input_mask], 0)

        if not pad_right:
            per_batch_new_inputs = tf.roll(per_batch_new_inputs, shift=input_mask_count, axis=0)
            per_batch_new_inputs_mask = tf.roll(per_batch_new_inputs_mask, shift=input_mask_count, axis=0)

        return per_batch_memory, per_batch_memory_mask, per_batch_new_inputs, per_batch_new_inputs_mask

    def attach_memory(self, inputs):
        inputs_mask = getattr(inputs, "_keras_mask", None)
        max_length = tf.shape(inputs)[1]
        if inputs_mask is None:
            inputs_mask = tf.ones([self.batch_size, max_length], dtype=tf.bool)
        _, _, new_inputs, new_inputs_mask = tf.vectorized_map(
            lambda item: self._prepend_memory_item(*item), elems=(tf.stop_gradient(self.memory), self.memory_mask, inputs, inputs_mask), warn=False
        )
        new_inputs._keras_mask = new_inputs_mask  # pylint: disable=protected-access
        return new_inputs

    def call(self, inputs):
        inputs_mask = getattr(inputs, "_keras_mask", None)
        if inputs_mask is None:
            inputs_mask = tf.ones([self.batch_size, tf.shape(inputs)[1]], dtype=tf.bool)
        _, _, new_memory, new_memory_mask = tf.vectorized_map(
            lambda item: self._prepend_memory_item(*item, pad_right=False), elems=(self.memory, self.memory_mask, inputs, inputs_mask), warn=False
        )
        new_memory = tf.slice(
            new_memory,
            begin=[0, tf.shape(new_memory)[1] - self.memory_length, 0],
            size=[-1, self.memory_length, -1],
        )
        new_memory_mask = tf.slice(
            new_memory_mask,
            begin=[0, tf.shape(new_memory_mask)[1] - self.memory_length],
            size=[-1, self.memory_length],
        )
        self.add_update([tf.keras.backend.update(self.memory, new_memory), tf.keras.backend.update(self.memory_mask, new_memory_mask)])
        new_memory._keras_mask = new_memory_mask  # pylint: disable=protected-access
        return new_memory

    def compute_output_shape(self, input_shape):
        return input_shape[0], self.memory_length, self.dmodel
