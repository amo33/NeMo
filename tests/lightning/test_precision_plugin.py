from collections import defaultdict
from unittest.mock import MagicMock

import pytest
import pytorch_lightning as pl
import torch
from megatron.core import parallel_state
from megatron.core.optimizer import OptimizerConfig
from torch import nn

from nemo import lightning as nl
from nemo.collections import llm
from nemo.lightning import megatron_parallel as mp


class DummyTokenizer:
    def __init__(self):
        self.vocab_size = 30000


class TestMegatronMixedPrecision:
    """Unit tests for the MegatronMixedPrecision class."""

    @pytest.mark.run_only_on('GPU')
    def test_precision_plugin_fp8_passed(self):
        """Test __init__ with default parameters."""

        class TrainerHook(nl.Trainer):
            def connect(self, model: pl.LightningModule) -> None:
                assert model.config.bf16 == False
                assert model.config.fp8 is None
                super().connect(model)
                assert model.config.fp8 == 'e4m3'
                assert model.config.bf16 == True

        trainer = TrainerHook(
            devices=2,
            accelerator="gpu",
            max_steps=2,
            strategy=nl.MegatronStrategy(
                tensor_model_parallel_size=2,
                sequence_parallel=True,
                ckpt_include_optimizer=False,
            ),
            plugins=nl.MegatronMixedPrecision(precision="bf16-mixed", fp8='e4m3'),
            limit_val_batches=0.0,
            num_sanity_val_steps=0,
        )

        optim = nl.MegatronOptimizerModule(
            config=OptimizerConfig(
                optimizer="adam",
                lr=1e-5,
                use_distributed_optimizer=False,
                fp16=True,
                params_dtype=torch.float32,
            ),
        )
        config = llm.Llama2Config7B()
        config.num_layers = 2
        model = llm.LlamaModel(config, tokenizer=DummyTokenizer(), optim=optim)
        trainer.strategy.connect(model)

    @pytest.mark.run_only_on('GPU')
    def test_precision_plugin_precision_params_override(self):
        """Test __init__ with default parameters."""
        trainer = nl.Trainer(
            devices=2,
            accelerator="gpu",
            max_steps=2,
            strategy=nl.MegatronStrategy(
                tensor_model_parallel_size=2,
                sequence_parallel=True,
                ckpt_include_optimizer=False,
            ),
            plugins=nl.MegatronMixedPrecision(precision="bf16-mixed"),
            limit_val_batches=0.0,
            num_sanity_val_steps=0,
        )

        optim = nl.MegatronOptimizerModule(
            config=OptimizerConfig(
                optimizer="adam",
                lr=1e-5,
                use_distributed_optimizer=False,
                fp16=True,
                params_dtype=torch.float32,
            ),
        )
        config = llm.Llama2Config7B()
        config.num_layers = 2
        config.fp16 = True
        config.bf16 = False
        model = llm.LlamaModel(config, tokenizer=DummyTokenizer(), optim=optim)
        trainer.strategy.connect(model)
        assert optim.config.bf16 is not None
        assert optim.config.fp16 is not None
        assert optim.config.bf16 == True
        assert optim.config.fp16 == False
        assert model.config.fp16 == False
        assert model.config.bf16 == True
