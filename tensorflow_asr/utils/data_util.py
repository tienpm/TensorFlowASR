# Copyright 2020 Huy Le Nguyen (@nglehuy)
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

# tf.data.Dataset does not work well for namedtuple so we are using dict

import os

import librosa
import tensorflow as tf


def load_and_convert_to_wav(
    path: str,
    sample_rate: int = None,
):
    wave, rate = librosa.load(os.path.realpath(os.path.expanduser(path)), sr=sample_rate, mono=True)
    return tf.audio.encode_wav(tf.expand_dims(wave, axis=-1), sample_rate=rate)


def read_raw_audio(audio: tf.Tensor):
    wave, _ = tf.audio.decode_wav(audio, desired_channels=1, desired_samples=-1)
    return tf.reshape(wave, shape=[-1])  # reshape for using tf.signal


def create_inputs(
    inputs,
    inputs_length,
    predictions=None,
    predictions_length=None,
):
    data = {
        "inputs": inputs,
        "inputs_length": inputs_length,
    }
    if predictions is not None:
        data["predictions"] = predictions
    if predictions_length is not None:
        data["predictions_length"] = predictions_length
    return data


def create_logits(
    logits,
    logits_length,
):
    return {
        "logits": logits,
        "logits_length": logits_length,
    }


def create_labels(
    labels,
    labels_length,
) -> dict:
    return {
        "labels": labels,
        "labels_length": labels_length,
    }
