# pylint: disable=line-too-long
import os

import tensorflow as tf

from tensorflow_asr.configs.config import DecoderConfig
from tensorflow_asr.featurizers.text_featurizers import WordPieceFeaturizer
from tensorflow_asr.utils import file_util

file_util.ENABLE_PATH_PREPROCESS = False

config_path = os.path.join(file_util.ROOT_DIRECTORY, "examples", "configs", "wp_whitespace.yml.j2")
print(config_path)
config = file_util.load_yaml(config_path)

decoder_config = DecoderConfig(config["decoder_config"])

text = "<pad> i'm good but it would have broken down after ten miles of that hard trail dawn came while they wound over the crest of the range and with the sun in their faces they took the downgrade it was well into the morning before nash reached logan"
text = "a b"


def test_wordpiece_featurizer():
    featurizer = WordPieceFeaturizer(decoder_config=decoder_config)
    print(featurizer.num_classes)
    print(text)
    indices = featurizer.extract(text)
    print(indices.numpy())
    batch_indices = tf.stack([indices, indices], axis=0)
    reversed_text = featurizer.iextract(batch_indices)
    print(reversed_text.numpy())
    upoints = featurizer.indices2upoints(indices)
    print(upoints.numpy())
