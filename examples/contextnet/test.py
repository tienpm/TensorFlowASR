# Copyright 2020 Huy Le Nguyen (@usimarit)
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

import os

import tensorflow as tf

from tensorflow_asr.configs.config import Config
from tensorflow_asr.helpers import dataset_helpers, exec_helpers, featurizer_helpers
from tensorflow_asr.models.transducer.contextnet import ContextNet
from tensorflow_asr.utils import cli_util, env_util, file_util

logger = env_util.setup_environment()

DEFAULT_YAML = os.path.join(os.path.abspath(os.path.dirname(__file__)), "config_wp.j2")


def main(
    config_path: str = DEFAULT_YAML,
    saved: str = None,
    mxp: str = "none",
    bs: int = None,
    device: int = 0,
    cpu: bool = False,
    output: str = "test.tsv",
):
    assert saved and output
    tf.keras.backend.clear_session()
    env_util.setup_seed()
    env_util.setup_devices([device], cpu=cpu)
    env_util.setup_mxp(mxp=mxp)

    config = Config(config_path)

    speech_featurizer, text_featurizer = featurizer_helpers.prepare_featurizers(config=config)
    batch_size = bs or config.learning_config.running_config.batch_size

    contextnet = ContextNet(**config.model_config, blank=text_featurizer.blank, vocab_size=text_featurizer.num_classes)
    contextnet.make(speech_featurizer.shape, batch_size=batch_size)
    contextnet.load_weights(saved, by_name=file_util.is_hdf5_filepath(saved))
    contextnet.summary()
    contextnet.add_featurizers(speech_featurizer, text_featurizer)

    test_dataset = dataset_helpers.prepare_testing_datasets(config=config, speech_featurizer=speech_featurizer, text_featurizer=text_featurizer)
    test_data_loader = test_dataset.create(batch_size)

    exec_helpers.run_testing(model=contextnet, test_dataset=test_dataset, test_data_loader=test_data_loader, output=output)


if __name__ == "__main__":
    cli_util.run(main)
