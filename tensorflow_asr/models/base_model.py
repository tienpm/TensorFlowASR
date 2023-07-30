# pylint: disable=attribute-defined-outside-init
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

import tensorflow as tf

from tensorflow_asr.models.layers.feature_extraction import FeatureExtraction
from tensorflow_asr.optimizers.accumulation import GradientAccumulator
from tensorflow_asr.utils import data_util, env_util, file_util

logger = tf.get_logger()


class BaseModelLayer(tf.keras.Model):  # pylint: disable=abstract-method
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._output_shape = None
        self.supports_masking = True

    def compute_output_shape(self, input_shape):
        return input_shape


class BaseModel(tf.keras.Model):
    def __init__(self, speech_config: dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.feature_extraction = FeatureExtraction(**speech_config)

    def summary(
        self,
        line_length=127,
        expand_nested=True,
        show_trainable=True,
        **kwargs,
    ):
        super().summary(line_length=line_length, expand_nested=expand_nested, show_trainable=show_trainable, **kwargs)

    def save(
        self,
        filepath,
        overwrite=True,
        include_optimizer=True,
        save_format=None,
        signatures=None,
        options=None,
        save_traces=True,
    ):
        with file_util.save_file(filepath) as path:
            super().save(
                filepath=path,
                overwrite=overwrite,
                include_optimizer=include_optimizer,
                save_format=save_format,
                signatures=signatures,
                options=options,
                save_traces=save_traces,
            )

    def save_weights(
        self,
        filepath,
        overwrite=True,
        save_format=None,
        options=None,
    ):
        with file_util.save_file(filepath) as path:
            super().save_weights(filepath=path, overwrite=overwrite, save_format=save_format, options=options)

    def load_weights(
        self,
        filepath,
        by_name=False,
        skip_mismatch=False,
        options=None,
    ):
        with file_util.read_file(filepath) as path:
            super().load_weights(filepath=path, by_name=by_name, skip_mismatch=skip_mismatch, options=options)

    @property
    def metrics(self):
        if not hasattr(self, "_tfasr_metrics"):
            self._tfasr_metrics = {}
        return list(self._tfasr_metrics.values())

    def reset_metrics(self):
        super().reset_metrics()
        self.reset_states()  # reset all stateful states also

    def add_custom_metric(self, metric: tf.keras.metrics.Metric):
        if not hasattr(self, "_tfasr_metrics"):
            self._tfasr_metrics = {}
        self._tfasr_metrics[metric.name] = metric

    def make(self, input_shape=[None], prediction_shape=[None], batch_size=None, **kwargs):
        """
        Custom function for building model (uses self.build so cannot overwrite that function)

        Parameters
        ----------
        input_shape : list, optional
            The shape of signal, by default [None]
        prediction_shape : list, optional
            The shape of prediction, by default [None]
        batch_size : int, optional
            Batch size, by default None
        """
        inputs = tf.keras.Input(shape=input_shape, batch_size=batch_size, dtype=tf.float32)
        inputs_length = tf.keras.Input(shape=[], batch_size=batch_size, dtype=tf.int32)
        predictions = tf.keras.Input(shape=prediction_shape, batch_size=batch_size, dtype=tf.int32)
        predictions_length = tf.keras.Input(shape=[], batch_size=batch_size, dtype=tf.int32)
        self(
            data_util.create_inputs(
                inputs=inputs,
                inputs_length=inputs_length,
                predictions=predictions,
                predictions_length=predictions_length,
            ),
            training=False,
        )

    def compile(
        self,
        loss,
        optimizer,
        run_eagerly=None,
        mxp="none",
        ga_steps=None,
        gwn_config=None,
        gradn_config=None,
        **kwargs,
    ):
        optimizer = tf.keras.optimizers.get(optimizer)
        if env_util.has_devices("TPU"):
            self.use_loss_scale = False
        else:
            self.use_loss_scale = mxp != "none"
            if self.use_loss_scale:
                optimizer = tf.keras.mixed_precision.LossScaleOptimizer(optimizer)
                logger.info("Using loss scale")
        if isinstance(ga_steps, int) and ga_steps > 1:
            self.use_ga = True
            self.ga = GradientAccumulator(ga_steps=ga_steps, trainable_variables=self.trainable_variables)
            logger.info(f"Using gradient accumulation with accumulate steps = {ga_steps}")
        else:
            self.use_ga = False
        self.gwn_config = gwn_config
        self.gradn = tf.keras.regularizers.get(gradn_config) if gradn_config else None
        self.distribute_reduction_method = "sum"
        self.add_custom_metric(tf.keras.metrics.Mean(name="loss"))
        super().compile(optimizer=optimizer, loss=loss, run_eagerly=run_eagerly, **kwargs)

    def call_logits(self, features, features_length, *args, training=False):
        raise NotImplementedError()

    def call(self, inputs, training=False):
        signals, signals_length = inputs["inputs"], inputs["inputs_length"]
        predictions, predictions_length = inputs["predictions"], inputs["predictions_length"]
        features, features_length = self.feature_extraction((signals, signals_length), training=training)
        logits, logits_length = self.call_logits(features, features_length, predictions, predictions_length, training=training)
        return data_util.create_logits(logits=logits, logits_length=logits_length)

    # -------------------------------- STEP FUNCTIONS -------------------------------------
    def apply_gwn(self) -> list:
        return []

    def remove_gwn(self, original_weights):
        pass

    def _get_global_batch_size(self, y_pred):
        global_batch_size = tf.shape(y_pred["logits"])[0] * self.distribute_strategy.num_replicas_in_sync
        return global_batch_size

    def _validate_and_get_metrics_result(self, logs):
        logs = super()._validate_and_get_metrics_result(logs)
        if "predictions" in logs:
            del logs["predictions"]
        return logs

    def train_step(self, batch):
        inputs, y_true = batch

        with tf.GradientTape() as tape:
            original_weights = self.apply_gwn()
            y_pred = self(inputs, training=True)
            self.remove_gwn(original_weights)
            per_sample_loss = self.loss(y_true=y_true, y_pred=y_pred)
            global_batch_size = self._get_global_batch_size(y_pred)
            loss = tf.nn.compute_average_loss(per_sample_loss, global_batch_size=global_batch_size)
            if self.use_loss_scale:
                scaled_loss = self.optimizer.get_scaled_loss(loss)

        if self.use_loss_scale:
            gradients = tape.gradient(scaled_loss, self.trainable_weights, unconnected_gradients=tf.UnconnectedGradients.ZERO)
            gradients = self.optimizer.get_unscaled_gradients(gradients)
        else:
            gradients = tape.gradient(loss, self.trainable_weights, unconnected_gradients=tf.UnconnectedGradients.ZERO)

        if self.use_ga:  # perform gradient accumulation
            self.ga.accumulate(gradients=gradients)
            gradients = self.ga.gradients

        if self.gradn is not None:
            if self.use_ga:
                gradients = tf.cond(self.ga.is_apply_step, lambda: self.gradn(step=self.optimizer.iterations, gradients=gradients), lambda: gradients)
            else:
                gradients = self.gradn(step=self.optimizer.iterations, gradients=gradients)

        self.optimizer.apply_gradients(zip(gradients, self.trainable_variables))

        if self.use_ga:
            tf.cond(self.ga.is_apply_step, self.ga.reset, lambda: None)

        self._tfasr_metrics["loss"].update_state(per_sample_loss)
        return {
            "loss": self._tfasr_metrics["loss"].result() / self.distribute_strategy.num_replicas_in_sync,
        }

    def test_step(self, batch):
        inputs, y_true = batch
        y_pred = self(inputs, training=False)
        per_sample_loss = self.loss(y_true=y_true, y_pred=y_pred)
        self._tfasr_metrics["loss"].update_state(per_sample_loss)
        return {m.name: m.result() / self.distribute_strategy.num_replicas_in_sync for m in self.metrics}

    def predict_step(self, batch):
        inputs, y_true = batch
        _tokens = self.recognize(**inputs)["tokens"]
        _beam_tokens = self.recognize_beam(**inputs)["tokens"]
        return {
            "_tokens": _tokens,
            "_beam_tokens": _beam_tokens,
            "_labels": y_true["labels"],
        }

    # -------------------------------- INFERENCE FUNCTIONS -------------------------------------

    def recognize(self, *args, **kwargs):
        """Greedy decoding function that used in self.predict_step"""
        raise NotImplementedError()

    def recognize_beam(self, *args, **kwargs):
        """Beam search decoding function that used in self.predict_step"""
        raise NotImplementedError()

    # ---------------------------------- TFLITE ---------------------------------- #

    def make_tflite_function(self, *args, **kwargs):
        pass
